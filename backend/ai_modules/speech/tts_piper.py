"""Streaming TTS with proper chunked playback and interrupt support."""
import asyncio
import difflib
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Tuple

import numpy as np
import sounddevice as sd
from piper import PiperVoice

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import TTSChunkEvent, TTSStartEvent, TTSEndEvent

VOICE_DIR = Path(__file__).parent / "piper_voices"
VOICE_NAME = "en_US-ryan-high"

_voice: PiperVoice | None = None
_playback_task: asyncio.Task | None = None
_audio_queue: asyncio.Queue | None = None
_stop_event: asyncio.Event | None = None


# ── Echo suppression (T-wake-word-executes-ambient-audio, item 1) ──────
#
# The assistant's own speech bleeds out of the speaker and back into the mic.
# Barge-in fires on loudness, Whisper transcribes the bleed into something
# plausible, and the router executes it — one legitimate wake cascading into a
# chain of misheard commands. Recording what we said here, at the only function
# that actually plays audio, lets the dispatch gate recognise its own voice.

# How long after playback ends a transcript of that same audio can still show
# up. Not speaker decay — the dominant term is the listener's own pipeline.
#
# A capture that starts while we are still talking runs until 800ms of trailing
# silence (_VAD_TRAILING_SILENCE_MS) or the 10s hard cap (_VAD_MAX_CAPTURE_S in
# wake_word.py), and only then does Whisper run. Measured live: an 8.6s capture
# reached this gate 9.6s after playback ended. A 3.0s tail — the value this
# started at — expired before the transcript existed and let a verbatim echo
# straight through.
#
# 10s capture cap + measured STT latency, rounded up. Not derived by import:
# wake_word imports this module, so reading its constants here would cycle.
_STT_LATENCY_BUDGET_S = 2.0
ECHO_TAIL_S = 10.0 + _STT_LATENCY_BUDGET_S

# Safety net for an utterance that never gets closed (a speak_stream generator
# abandoned without being exhausted or closed). Without it a leaked entry would
# pin the gate open forever. Longer than any single sentence we speak.
_UNFINISHED_MAX_S = 60.0

# Absolute ceiling on one entry's liveness, regardless of burst. Stops a new
# burst from resurrecting a sentence spoken minutes ago and still sitting in
# the ring.
_UTTERANCE_MAX_LIFETIME_S = 60.0

# A couple of turns' worth of streamed sentences.
_RECENT_SPOKEN_CAP = 10

# Fraction of the transcript's words that must appear, in order, inside a
# recent utterance for it to count as echo.
#
# Echo is not a paraphrase — the words *are* our words, so genuine echo scores
# at or near 1.0 even when the mic only caught a fragment. The threshold is set
# high to protect the case that actually collides: the user repeating a command
# the assistant just narrated. "playing music on spotify" (spoken) vs "play
# music on spotify" (user) scores 0.75 and survives; the gerund/imperative
# swap costs a token and that is exactly the signal we want to keep.
ECHO_CONTAINMENT_RATIO = 0.8

# Below this, containment is coincidence rather than evidence — and short
# transcripts are precisely where real commands live ("open chrome", "volume
# up"). Never suppress them; a short echo fragment getting through is the
# cheaper error.
ECHO_MIN_TOKENS = 3

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class _Utterance:
    """One thing we said, and the window in which it can still be misheard."""
    text: str
    tokens: tuple[str, ...]
    started_at: float
    ended_at: float | None = None


_recent_spoken: deque[_Utterance] = deque(maxlen=_RECENT_SPOKEN_CAP)
# speak_stream runs on the daemon's event loop; was_recently_spoken is called
# from the wake-word listener's thread. Cheap lock, no contention.
_spoken_lock = threading.Lock()


def _normalize(text: str) -> tuple[str, ...]:
    """Lowercase, drop punctuation, collapse whitespace → word tuple."""
    return tuple(_WORD_RE.findall((text or "").lower()))


def _note_spoken(text: str) -> _Utterance:
    """Record an utterance as live-from-now. Closed by _close_utterance."""
    utterance = _Utterance(
        text=text,
        tokens=_normalize(text),
        started_at=time.monotonic(),
    )
    with _spoken_lock:
        _recent_spoken.append(utterance)
    return utterance


def _close_utterance(utterance: _Utterance) -> None:
    """Mark playback finished — the tail starts counting from here."""
    with _spoken_lock:
        if utterance.ended_at is None:
            utterance.ended_at = time.monotonic()


def _live_utterances(now: float) -> list[_Utterance]:
    """Everything from the current speaking burst.

    Liveness is a property of the burst, not the individual sentence. Streaming
    TTS closes sentence 1 while sentences 2-5 are still queued, and a capture
    opened during sentence 3 can be holding sentence 1's audio. Measured live:
    a fragment of sentence 2 of a 3-sentence answer reached the dispatch gate
    13s after *that sentence* ended but only 9s after the assistant stopped
    talking — a per-sentence tail let a verbatim echo through.

    So the ring expires as a unit, ECHO_TAIL_S after the last word. Each entry
    still gets an absolute ceiling so a fresh burst can't resurrect something
    said minutes ago.
    """
    if not _recent_spoken:
        return []

    speaking = any(
        u.ended_at is None and (now - u.started_at) < _UNFINISHED_MAX_S
        for u in _recent_spoken
    )
    if not speaking:
        ends = [u.ended_at for u in _recent_spoken if u.ended_at is not None]
        if not ends or (now - max(ends)) >= ECHO_TAIL_S:
            return []

    return [
        u for u in _recent_spoken
        if u.ended_at is None or (now - u.ended_at) < _UTTERANCE_MAX_LIFETIME_S
    ]


def _containment(spoken: tuple[str, ...], transcript: tuple[str, ...]) -> float:
    """Fraction of `transcript` that appears, in order, inside `spoken`.

    Deliberately asymmetric. The mic catches a *fragment* of a sentence far
    more often than the whole thing, so a similarity score over both strings
    would score a perfectly-captured 6-word fragment of a 40-word answer near
    zero. What matters is whether everything we heard came from something we
    said, not whether we said only that.
    """
    if not transcript or not spoken:
        return 0.0
    matcher = difflib.SequenceMatcher(None, spoken, transcript, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(transcript)


def was_recently_spoken(transcript: str) -> bool:
    """Is this transcript the assistant hearing itself?

    True when `transcript` is substantially contained in something spoken
    within the live window. Callers should drop such transcripts before
    dispatch — see trigger._handle_wake_async.
    """
    tokens = _normalize(transcript)
    if len(tokens) < ECHO_MIN_TOKENS:
        return False

    now = time.monotonic()
    with _spoken_lock:
        live = _live_utterances(now)

    if any(_containment(u.tokens, tokens) >= ECHO_CONTAINMENT_RATIO for u in live):
        return True

    # A capture does not respect our sentence boundaries. Streaming TTS pushes
    # one utterance per sentence, and the mic happily records across two of
    # them — such a transcript scores ~0.5 against each half and would survive
    # a per-utterance check. Test the live window as one span too.
    spanning = tuple(token for u in live for token in u.tokens)
    return _containment(spanning, tokens) >= ECHO_CONTAINMENT_RATIO


def recent_spoken_snapshot() -> list[tuple[str, float | None]]:
    """(text, ended_at) for everything still in the ring. Diagnostics only."""
    with _spoken_lock:
        return [(u.text, u.ended_at) for u in _recent_spoken]


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        model_path = VOICE_DIR / f"{VOICE_NAME}.onnx"
        config_path = VOICE_DIR / f"{VOICE_NAME}.onnx.json"
        if not model_path.exists() or not config_path.exists():
            raise RuntimeError(
                f"Piper voice files missing in {VOICE_DIR}. "
                f"Expected {VOICE_NAME}.onnx + .onnx.json"
            )
        _voice = PiperVoice.load(str(model_path), config_path=str(config_path))
    return _voice


def generate_audio(text: str) -> Tuple[bytes, int]:
    """Synthesize `text` and return raw PCM bytes (16kHz) and sample rate.
    
    Kept for backward compatibility with tests and legacy callers.
    """
    voice = _get_voice()
    chunks = list(voice.synthesize(text))
    if not chunks:
        return b"", 0
    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    return audio.tobytes(), rate


async def _audio_player() -> None:
    """Background task that plays audio chunks from queue."""
    global _audio_queue, _stop_event
    
    if _audio_queue is None or _stop_event is None:
        return
    
    stream = None
    try:
        # Get first chunk to determine sample rate
        first_chunk = await _audio_queue.get()
        if first_chunk is None:
            return
        
        rate = first_chunk.get("rate", 22050)
        audio_data = first_chunk.get("audio", np.array([], dtype=np.int16))
        
        if audio_data.size > 0:
            stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16")
            stream.start()
            stream.write(audio_data)
        
        # Play remaining chunks
        while not _stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(_audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            
            if chunk is None:  # End signal
                break
            
            audio_data = chunk.get("audio", np.array([], dtype=np.int16))
            if audio_data.size > 0 and stream:
                stream.write(audio_data)
    
    except Exception as e:
        print(f"[TTS] Audio player error: {e}")
    finally:
        if stream:
            stream.stop()
            stream.close()
        # Drain queue
        while not _audio_queue.empty():
            try:
                _audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


async def speak_stream(text: str) -> AsyncGenerator[dict, None]:
    """True streaming TTS — plays chunks as they're synthesized.
    
    Yields progress dicts: {"status": "started|playing|finished", "text": str, "progress": float}
    """
    global _playback_task, _audio_queue, _stop_event

    # Record before synthesis: the mic can start hearing us the moment the
    # first chunk hits the speaker, which is before this function returns.
    utterance = _note_spoken(text)

    voice = _get_voice()

    # Initialize streaming infrastructure
    _audio_queue = asyncio.Queue(maxsize=10)
    _stop_event = asyncio.Event()
    _stop_event.clear()
    
    # Start audio player task
    _playback_task = asyncio.create_task(_audio_player())
    
    # Emit start event
    bus = get_bus()
    bus.publish(TTSStartEvent(text=text), priority=Priority.HIGH)
    
    yield {"status": "started", "text": text, "progress": 0.0}
    
    try:
        iterator = voice.synthesize(text)
        chunk_count = 0
        
        for chunk in iterator:
            if _stop_event.is_set():
                break
            
            audio_array = chunk.audio_int16_array
            rate = chunk.sample_rate
            
            # Queue chunk for playback
            await _audio_queue.put({"audio": audio_array, "rate": rate})
            
            chunk_count += 1
            yield {"status": "playing", "text": text, "progress": chunk_count * 0.1}
            
            # Small delay to let audio player start
            await asyncio.sleep(0.01)
        
        # Signal end
        await _audio_queue.put(None)
        
        if _playback_task:
            await _playback_task
        
        bus.publish(TTSEndEvent(text=text), priority=Priority.HIGH)
        yield {"status": "finished", "text": text, "progress": 1.0}
        
    except Exception as e:
        print(f"[TTS] Streaming error: {e}")
        _stop_event.set()
        yield {"status": "error", "text": text, "error": str(e)}
    finally:
        # Start the echo tail here, not at TTSEndEvent: this also runs when
        # playback was cut short by barge-in or an error, and those are exactly
        # the moments the mic is most likely to be holding a capture of us.
        _close_utterance(utterance)
        # Cleanup
        _audio_queue = None
        _stop_event = None
        _playback_task = None


def speak(text: str) -> dict:
    """Synthesize and play text (blocking synthesis, non-blocking playback)."""
    # Use streaming internally but wait for completion
    async def _run():
        async for _ in speak_stream(text):
            pass
    
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # If already in async context, create task
        task = loop.create_task(_run())
        # Don't await - non-blocking
        return {"status": "started", "text": text}
    except RuntimeError:
        # No running loop, run in new loop
        asyncio.run(_run())
        return {"status": "finished", "text": text}


def stop_speech() -> None:
    """Immediately stop any in-progress speech playback."""
    global _stop_event, _audio_queue, _playback_task
    
    if _stop_event:
        _stop_event.set()
    
    # Clear queue
    if _audio_queue:
        while not _audio_queue.empty():
            try:
                _audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    # Also stop sounddevice directly
    sd.stop()
    
    print("[TTS] Speech interrupted")


def is_speaking() -> bool:
    """Check if TTS is currently playing."""
    return _playback_task is not None and not _playback_task.done()