import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Generator

import numpy as np
import sounddevice as sd
import vosk

from backend.core.agents.pending_confirmation import store as _pending_store
from backend.core.dogfooding import ledger as dogfooding_ledger
from backend.core.state import AssistantState, manager as state_manager
from backend.server.config import settings

vosk.SetLogLevel(-1)

MODELS_DIR = Path(__file__).resolve().parents[1] / "ai_modules" / "speech" / "vosk_models"
DEFAULT_MODEL = "vosk-model-small-en-us-0.15"

# VAD tuning for command capture. RMS values are int16-amplitude scaled
# (full-scale = 32768). 400 is well above mic noise floor on consumer
# laptops but below normal speech (~1500-3000).
_VAD_RMS_THRESHOLD = 50  # ponytail: lowered from 400 for quieter mics
_VAD_TRAILING_SILENCE_MS = 800  # stop after this much silence post-speech
_VAD_MAX_CAPTURE_S = 10.0  # hard cap so a stuck mic doesn't hang forever
_VAD_INITIAL_WAIT_S = 3.0  # how long to wait for the user to start speaking

_FOLLOWUP_WINDOW_S = 3.0        # seconds the follow-up window stays open
_FOLLOWUP_MAX_EMPTY = 2

# How long a new turn waits for the previous one to unwind before starting
# anyway. Generous: the previous turn has already been interrupted, so this is
# a safety valve against a wedged turn, not a normal wait.
_TURN_HANDOVER_TIMEOUT_S = 15.0


def _has_followup_content(partial: str) -> bool:
    """Legacy word-shape gate. DO NOT use against this listener's partials.

    Kept because it is still the right check for a free-vocabulary
    recognizer, but ours is grammar-restricted to [wake_phrase, "[unk]"]:
    every out-of-vocabulary word — i.e. everything the user actually says
    after the wake phrase — comes back as the literal token "[unk]", which
    has no alphabetic characters. Measured against the real model, this
    returned False for every frame of two recorded speech clips and True
    only on the frames containing "onyx". Gating anything on it means
    gating on "did they say the wake word again". Use `_partial_grew`.
    """
    return any(len(w) >= 2 and w.isalpha() for w in partial.split())


def _partial_token_count(partial: str) -> int:
    """Tokens Vosk has decoded so far in the current utterance."""
    return len(partial.split())


def _partial_grew(partial: str, previous_tokens: int) -> bool:
    """True when Vosk decoded NEW audio-as-speech on this frame.

    Two measured properties of the real recognizer drive this:

      1. Loud non-speech does not decode at all. A click train at 3085 RMS
         and a 220Hz tone at 5656 RMS — both far above the 800 barge-in
         threshold and above the 2854 RMS room transients that were
         self-interrupting playback — produce an empty partial and an empty
         FinalResult. The acoustic model rejects them. This is the signal
         that separates a door slam from a person.
      2. PartialResult is CUMULATIVE. It keeps returning the whole
         accumulated string on subsequent silent frames, so "is the partial
         non-empty" latches True after the first utterance and never
         un-latches until Reset(). Only an INCREASE in the token count is
         per-frame evidence; the count is the gate, not the text.
    """
    return _partial_token_count(partial) > previous_tokens



class WakeWordListener:
    """Continuously samples the mic and fires `on_wake(captured_audio_bytes)`
    when `wake_phrase` is recognised.

    Two callbacks:
      - on_wake_detected(): fires the instant the wake phrase is recognised,
        BEFORE any audio is captured. Use it to flash the UI and play a
        chime so the user gets immediate feedback.
      - on_wake(audio_bytes): fires after the command audio has been
        captured (variable length, VAD-controlled).

    Capture length is no longer fixed: we read chunks from the mic, look
    for ~700ms of silence following speech, and stop. Hard caps at 8s.
    """

    def __init__(
        self,
        on_wake: Callable[[bytes], Any],
        on_wake_detected: Optional[Callable[[], None]] = None,
        on_barge_in: Optional[Callable[[float], None]] = None,
        wake_phrase: str = "onyx",
        capture_seconds: float = 2.5,  # legacy arg, ignored by VAD path
        sample_rate: int = 16000,
        device: Optional[int] = None,
        model_name: str = DEFAULT_MODEL,
    ):
        model_path = MODELS_DIR / model_name
        if not model_path.exists():
            raise RuntimeError(
                f"Vosk model not found at {model_path}. "
                f"Run: python tools/download_vosk_model.py"
            )

        self.model = vosk.Model(str(model_path))
        self.recognizer = vosk.KaldiRecognizer(
            self.model, sample_rate, json.dumps([wake_phrase, "[unk]"])
        )
        self.wake_phrase = wake_phrase.lower()
        self.on_wake = on_wake
        self.on_wake_detected = on_wake_detected
        self.on_barge_in = on_barge_in
        self.capture_seconds = capture_seconds  # unused; kept for arg compat
        self.sample_rate = sample_rate
        self.device = device
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._capturing = False
        # Phase 4A: consecutive high-RMS chunks while state == SPEAKING;
        # resets to 0 on any low-RMS chunk. When it reaches
        # settings.barge_in_debounce_frames, we fire barge-in.
        self._barge_in_frames = 0
        # Token count of the last partial we saw, so a frame can be judged
        # as "Vosk decoded something new" rather than "the mic was loud".
        self._partial_tokens = 0
        # Sticky within one debounce run: did ANY frame of this run carry new
        # decoded speech? Vosk emits a token every few frames, not every
        # frame, so requiring growth on all N would never pass.
        self._barge_in_saw_speech = False
        # Follow-up bookkeeping. Instance state rather than locals in listen()
        # because the turn now finishes on a worker thread, which is what
        # decides whether the window opens.
        self._followup_until: float = 0.0   # monotonic; <= now == closed
        self._empty_in_a_row: int = 0
        self._turn_thread: Optional[threading.Thread] = None

    def _cb(self, indata, _frames, _time, _status):
        self.queue.put(bytes(indata))

    def _check_barge_in(self, rms: float, partial: str = "") -> bool:
        """Return True iff, during SPEAKING, loud audio that Vosk actually
        decoded as speech passed the debounce.

        `partial` is the recognizer's cumulative PartialResult for the frame.
        Loudness alone used to be the whole gate, and room-noise transients
        measured at 2854 RMS against an 800 threshold self-interrupted
        playback. Non-speech does not decode (see `_partial_grew`), so we
        additionally require that at least one frame of the debounce run
        added a token. `settings.barge_in_require_speech = False` restores
        the old loudness-only behaviour.

        Kept as a separate method so tests can drive the sequence directly
        without needing a running mic stream. Side effects: mutates
        `_barge_in_frames`, `_barge_in_saw_speech`, `_partial_tokens`.
        """
        grew = _partial_grew(partial, self._partial_tokens)
        self._partial_tokens = _partial_token_count(partial)

        if (
            not settings.enable_barge_in
            or state_manager.current != AssistantState.SPEAKING
        ):
            # Outside SPEAKING or disabled — always reset so partial debounce
            # doesn't leak across a state transition.
            self._barge_in_frames = 0
            self._barge_in_saw_speech = False
            return False
        if rms > settings.barge_in_rms_threshold:
            self._barge_in_frames += 1
            self._barge_in_saw_speech = self._barge_in_saw_speech or grew
            speech_ok = self._barge_in_saw_speech or not settings.barge_in_require_speech
            if self._barge_in_frames >= settings.barge_in_debounce_frames and speech_ok:
                self._barge_in_frames = 0
                self._barge_in_saw_speech = False
                return True
            return False
        # RMS below threshold — reset debounce.
        self._barge_in_frames = 0
        self._barge_in_saw_speech = False
        return False

    def _start_turn(self, audio: bytes) -> None:
        """Run the turn off the listen loop.

        `on_wake` is handle_wake, which runs the whole turn synchronously —
        and `_run_brain_streaming` ends in `await sq.finish()`, which drains
        the sentence queue, so it does not return until the last word has been
        SPOKEN. Calling it inline meant `_capturing` stayed set for the entire
        reply and every mic frame hit the `continue` at the top of the loop.
        The listener was deaf for exactly the window in which barge-in, the
        wake word and "stop" all need to work. `[TTS] Speech interrupted`
        still appeared in the log because on_wake_detected calls stop_speech()
        unconditionally, which prints whether or not anything was playing —
        that is what made interruption look like it worked.

        Turn BODIES are serialized; the listen loop is not. That distinction
        is the whole design: the loop must keep reading the mic (or barge-in
        and "stop" are unreachable), but two turns must never execute at once.

        An earlier version of this let them overlap, on the reasoning that
        "playback state is per-call, see T-tts-loop-globals". That was true of
        tts_piper._PlaybackSession and FALSE of SentenceQueue, which is still
        a module-level singleton: start() binds a fresh queue AND a consumer
        task to the calling loop, and handle_wake runs asyncio.run() per
        capture — so a second turn on a second thread overwrote `_task` while
        the first was still awaiting it. Live result:

            got Future <Task ... SentenceQueue._consumer()> attached to a
            different loop
            -> "Sorry, I encountered an error"

        plus "await wasn't used with future" and GeneratorExit noise on
        shutdown. Roughly one turn in four died that way.

        The join happens INSIDE the new worker, never on the listen loop — a
        join there would restore exactly the deafness this method exists to
        remove. The wait is short in practice because a new trigger has
        already run on_barge_in / on_wake_detected, which stop speech and
        interrupt the commander, so the previous turn is already unwinding.
        """
        previous = self._turn_thread

        def _run() -> None:
            # Let the previous turn finish before touching any of the
            # singletons it owns. Bounded so a wedged turn cannot deafen us
            # forever; if it does time out we proceed and accept the risk,
            # because silently dropping the user's command is worse.
            if previous is not None and previous.is_alive():
                previous.join(timeout=_TURN_HANDOVER_TIMEOUT_S)
                if previous.is_alive():
                    print(f"[wake] previous turn still running after "
                          f"{_TURN_HANDOVER_TIMEOUT_S:.0f}s; starting anyway")

            command_handled = False
            try:
                result = self.on_wake(audio)
                command_handled = result is None or bool(result)
            except Exception as e:
                print(f"[wake] on_wake handler raised: {e}")
            finally:
                # ponytail: one-line dogfooding hook — survived wake=True/False
                try:
                    dogfooding_ledger.record_wake(command_handled)
                except Exception:
                    pass
                if command_handled:
                    self._empty_in_a_row = 0
                    window = _FOLLOWUP_WINDOW_S
                    # If the turn ended by ASKING something, keep listening.
                    # 3s begins when the assistant stops speaking, so after
                    # "I need your permission to close app. Should I proceed?"
                    # the user hears it, thinks, answers — and by then the
                    # window has shut. Reported live as "not even reading my
                    # proceed command": there was no transcript at all,
                    # because nothing was listening. Asking a question and
                    # then not waiting for the answer is its own bug.
                    try:
                        if _pending_store.awaiting_answer():
                            window = settings.confirmation_followup_window_s
                    except Exception:
                        pass
                    self._followup_until = time.monotonic() + window
                    print(f"[wake] follow-up window open for {window:.0f}s")
                else:
                    self._empty_in_a_row += 1
                    if self._empty_in_a_row >= _FOLLOWUP_MAX_EMPTY:
                        self._followup_until = 0.0
                        self._empty_in_a_row = 0
                        print(f"[wake] follow-up closed after {_FOLLOWUP_MAX_EMPTY} empty captures; say {self.wake_phrase!r} again")
                    else:
                        print(f"[wake] empty capture ({self._empty_in_a_row}/{_FOLLOWUP_MAX_EMPTY}); follow-up still open")

        self._turn_thread = threading.Thread(target=_run, name="wake-turn", daemon=True)
        self._turn_thread.start()

    def _drain(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _capture(self, initial: Optional[list[bytes]] = None) -> bytes:
        """Read mic chunks until VAD says the user stopped speaking.

        Two phases:
          1. Wait up to _VAD_INITIAL_WAIT_S for the first speech chunk.
          2. Once speech started, accumulate chunks and stop once
             _VAD_TRAILING_SILENCE_MS of silence has passed.
        Hard cap at _VAD_MAX_CAPTURE_S total.

        `initial` is any audio already collected by the caller (e.g. the
        chunk that triggered follow-up mode, or audio that arrived during
        wake recognition). It seeds the buffer so we don't lose it.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        for c in chunks:
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _VAD_RMS_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            is_speech = rms > _VAD_RMS_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        # User never started talking — bail rather than hang.
                        break

        return b"".join(chunks)

    def _capture_chunks(self, initial: Optional[list[bytes]] = None) -> Generator[bytes, None, None]:
        """Yield mic chunks until VAD says the user stopped speaking.
        
        Generator version for streaming STT integration.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        for c in chunks:
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _VAD_RMS_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            is_speech = rms > _VAD_RMS_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            yield chunk  # Yield each chunk for streaming STT

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        break

    def listen(self) -> None:
        """Continuously listen for wake word and fire callbacks."""
        self._running = True
        print(f"[wake] listening for {self.wake_phrase!r}... (Ctrl+C to stop)")
        # Smaller blocksize (125ms) gives PartialResult more frequent updates
        # AND lets follow-up RMS triggering react fast. Trade-off: more CPU.
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=2000,
            device=self.device,
            callback=self._cb,
        ):
            # Persists ACROSS frames on purpose: PartialResult is cumulative,
            # so the token-growth gates need the previous frame's string as a
            # baseline. Re-initialising it per frame would make every loud
            # frame after a quiet one look like fresh speech.
            partial: str = ""

            while self._running:
                try:
                    data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._capturing:
                    continue

                now = time.monotonic()
                in_followup = now < self._followup_until

                trigger = False
                is_barge_in = False
                initial_audio: list[bytes] = []
                trigger_label = ""

                arr = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

                try:
                    if rms > _VAD_RMS_THRESHOLD:
                        self.recognizer.AcceptWaveform(data)
                        partial_json = json.loads(self.recognizer.PartialResult())
                        partial = (partial_json.get("partial") or "").lower()

                        if self.wake_phrase in partial.split():
                            trigger = True
                            trigger_label = f"wake: {partial!r} (rms={rms:.0f})"
                            self.recognizer.Reset()
                            partial = ""
                            self._partial_tokens = 0
                            self._empty_in_a_row = 0
                            state_manager._voice_trigger_source = "wake"
                        elif in_followup and _partial_grew(partial, self._partial_tokens):
                            # T-wake-word-executes-ambient-audio item 2: gate the
                            # follow-up window on CONTENT, not loudness. Near-silence
                            # after the speaker cut off still clears rms>500 and
                            # Whisper hallucinated whole commands on it ("I am
                            # working out." ran a full LLM turn). Vosk decodes no
                            # tokens from that audio, so the count does not move.
                            #
                            # This was _has_followup_content, which asked for
                            # alphabetic words. Under our restricted grammar the
                            # user's actual words arrive as "[unk]" and that check
                            # is False for every frame of real speech — measured —
                            # so the follow-up window only ever reopened on a second
                            # "onyx", which is just the wake path.
                            trigger = True
                            trigger_label = f"followup: {partial!r} (rms={rms:.0f})"
                            initial_audio = [data]
                            state_manager._voice_trigger_source = "followup"
                            self.recognizer.Reset()
                            partial = ""
                            self._partial_tokens = 0

                except Exception:
                    continue

                # Phase 4A: barge-in — if the user speaks WHILE TTS is playing,
                # interrupt playback and treat the utterance as a new command.
                # RMS + debounce is a coarse mitigation for TTS-bleeding-into-
                # mic false-fires; a loud speaker close to the mic will still
                # false-fire (out of scope — future AEC work).
                if not trigger and self._check_barge_in(rms, partial):
                    trigger = True
                    is_barge_in = True
                    trigger_label = f"barge-in (rms={rms:.0f})"
                    initial_audio = [data]
                    state_manager._voice_trigger_source = "barge_in"

                if not trigger:
                    continue

                print(f"[wake] heard {trigger_label}")
                self._capturing = True
                # Route the pre-capture callback: barge-in gets its own hook
                # (so the trigger can also publish SpeechInterruptedEvent),
                # falling back to on_wake_detected for the normal wake path.
                if is_barge_in and self.on_barge_in is not None:
                    try:
                        self.on_barge_in(rms)
                    except Exception as e:
                        print(f"[wake] on_barge_in raised: {e}")
                elif self.on_wake_detected is not None:
                    try:
                        self.on_wake_detected()
                    except Exception as e:
                        print(f"[wake] on_wake_detected raised: {e}")

                # Capture stays inline: it reads the same mic queue this loop
                # does, so they cannot both run.
                try:
                    audio = self._capture(initial=initial_audio)
                except Exception as e:
                    print(f"[wake] capture raised: {e}")
                    audio = b""
                finally:
                    try:
                        self.recognizer.Reset()
                    except Exception:
                        pass
                    # Reset() empties PartialResult; the growth baseline has to
                    # follow it down or the next utterance's first tokens look
                    # like no growth at all.
                    partial = ""
                    self._partial_tokens = 0
                    self._barge_in_saw_speech = False
                    self._drain()
                    # Cleared HERE, not after the turn. Holding it until
                    # on_wake returned made the listener deaf for the entire
                    # reply — see _run_turn.
                    self._capturing = False

                # The turn — planning, tools, and every spoken sentence — runs
                # on a worker so this loop keeps reading the mic. That is what
                # makes barge-in and "stop" possible at all while speaking.
                self._start_turn(audio)

    def stop(self) -> None:
        self._running = False
