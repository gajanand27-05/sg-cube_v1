import logging
import re
import threading
import time
from pathlib import Path
from typing import Generator

import numpy as np

from backend.ai_modules.speech.stt_manager import get_model  # noqa: F401
from backend.server.config import settings

log = logging.getLogger(__name__)

# get_model used to live here as an @lru_cache(maxsize=1) pinned to
# device="cpu", compute_type="int8" — so the GPU was never used, accuracy was
# capped by int8 quantisation, and the model was held for the life of the
# process with no way to switch when the power source changed. It now comes
# from stt_manager, which picks the profile and owns the lifetime. Re-exported
# here because callers already import it from this module.


# Initial-prompt biasing for Whisper. Single-word commands ("lock",
# "next", "stop") often get rewritten to common everyday words ("luck",
# "neck") because they have no context. The prompt below is prose-style
# (NOT a comma-separated list — comma lists teach Whisper to split words
# like "notepad" into "note, pad"). Reads as if a previous user just
# spoke similar commands, which is how Whisper's prompt mechanism is
# designed to work.
_COMMAND_PROMPT = (
    # "Onyx" leads this on purpose. The captured audio starts with the wake
    # word (the pre-roll includes it), and the decoder had never been primed
    # for that name — so it reinterpreted the wake word TOGETHER with the
    # first word of the command. Measured live against clean TTS speech:
    #     "Onyx, who is the CEO of Nvidia" -> 'I am the CEO of Nvia.'
    #     "Onyx. What's the weather"       -> 'And of course the weather.'
    # When the name survives as its own token the command transcribes intact
    # ('Onyx, what is the latest tech news?'), which is what points at
    # priming rather than acoustics.
    #
    # KEYWORDS, NOT SENTENCES. The first draft opened with "I am talking to my
    # voice assistant, which is called Onyx." and Whisper handed that back
    # verbatim as a transcript when the audio did not decode — the user said
    # "play mungaru male music on youtube" (Kannada, force-decoded as English)
    # and got the prompt's opening sentence read back at them. The older
    # prompt did the same in milder form ('i am using a closed notepad.').
    # A keyword list conditions the decoder just as well and does not read
    # like something a person said, so there is far less to emit whole.
    # is_prompt_echo() is the backstop if this ever drifts back into prose.
    "Onyx. Voice commands: open notepad, close chrome, lock the screen, "
    "play music on youtube, search google, what time is it, whats the "
    "weather, read the news, set a reminder, translate to spanish, "
    "summarize this article, stop, cancel, never mind. Apps: notepad, "
    "chrome, firefox, vscode, spotify, whatsapp, discord, telegram, "
    "calculator, explorer."
)

# Below this many words, an overlap with the prompt is coincidence — the
# prompt lists real commands ("open notepad", "what time is it"), and
# swallowing those would be far worse than the echo it guards: working speech
# would vanish with no error anywhere. The observed echoes are whole clauses.
_PROMPT_ECHO_MIN_WORDS = 8


def _normalize_for_echo(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


_PROMPT_NORMALIZED = None


def is_prompt_echo(text: str) -> bool:
    """True when a transcript is really Whisper reciting its own prompt.

    Whisper emits its initial_prompt when the audio gives it nothing to work
    with — silence, noise, or speech in a language it is being forced out of.
    That output is indistinguishable from a real command downstream: it is
    fluent, confident, and was dispatched to the router.

    Matches a long verbatim run rather than any overlap, because the prompt
    deliberately contains real commands.
    """
    global _PROMPT_NORMALIZED
    norm = _normalize_for_echo(text)
    if len(norm.split()) < _PROMPT_ECHO_MIN_WORDS:
        return False
    if _PROMPT_NORMALIZED is None:
        _PROMPT_NORMALIZED = _normalize_for_echo(_COMMAND_PROMPT)
    return norm in _PROMPT_NORMALIZED

# ── Phase C1: silero-vad integration ──
_SILERO_VAD = None
_silero_lock = threading.Lock()


def _get_silero_vad():
    global _SILERO_VAD
    # Double-checked locking: the wake-word listener and the capture thread both
    # reach this. Unguarded, both see None and both run torch.hub.load — two
    # model loads racing on the same hub cache directory.
    if _SILERO_VAD is None:
        with _silero_lock:
            if _SILERO_VAD is None:
                import torch
                _SILERO_VAD, _ = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    onnx=True,
                )
    return _SILERO_VAD


def vad_speech_prob(chunk: np.ndarray, sample_rate: int = 16000) -> float:
    """Return speech probability (0.0–1.0) for a single audio chunk via silero-vad."""
    import torch
    model = _get_silero_vad()
    return float(model(torch.from_numpy(chunk), sample_rate).item())


# ── Phase C1: Streaming VAD iterator ──
SILERO_VAD_THRESHOLD = 0.5
VAD_TRAILING_SILENCE_MS = 600
VAD_MIN_SPEECH_MS = 100


def _filter_speech_chunks(
    chunk_iterable: Generator[bytes, None, None],
    sample_rate: int = 16000,
) -> Generator[np.ndarray, None, None]:
    """Yield numpy arrays of speech-only audio chunks using silero-vad.

    Drops non-speech chunks before and after speech. Handles trailing
    silence detection so the caller gets a clean utterance.
    """
    bytes_per_ms = sample_rate * 2 // 1000
    trailing_bytes = VAD_TRAILING_SILENCE_MS * bytes_per_ms
    min_speech_bytes = VAD_MIN_SPEECH_MS * bytes_per_ms

    speech_seen = False
    speech_buffer: list[np.ndarray] = []
    trailing_silence_bytes = 0

    for chunk_bytes in chunk_iterable:
        arr = np.frombuffer(chunk_bytes, dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            continue
        prob = vad_speech_prob(arr, sample_rate)
        if prob > SILERO_VAD_THRESHOLD:
            speech_seen = True
            trailing_silence_bytes = 0
            speech_buffer.append(arr)
        elif speech_seen:
            trailing_silence_bytes += len(chunk_bytes)
            speech_buffer.append(arr)
            if trailing_silence_bytes >= trailing_bytes:
                break

    if not speech_seen:
        return

    total_speech = np.concatenate(speech_buffer)
    if len(total_speech) < min_speech_bytes:
        return
    yield total_speech


def transcribe(audio_path: str | Path) -> dict:
    """Transcribe a short voice-command clip from a WAV file.

    Tuned for ~2s English command audio:
      - language="en" — skip Whisper's language-detect pass (~200ms saved,
        avoids occasional misidentification on noisy short clips).
      - beam_size=1 — greedy decoding.
      - vad_filter=True — drop silence/noise around the spoken bit.
      - initial_prompt — biases decoding toward command vocabulary.
    """
    model = get_model()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        initial_prompt=_COMMAND_PROMPT,
    )

    return _collect_segments(segments, info)


_cpu_model = None
_cpu_lock = threading.Lock()


def transcribe_array_cpu(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Last-resort offline transcription. CPU ONLY, always.

    Deliberately does NOT go through stt_manager.get_model(): that resolves
    select_profile(), which under STT_PROFILE=accurate returns medium/cuda —
    2091 MiB of GPU that the whole move to cloud STT existed to free. A
    fallback that quietly grabs the GPU would reintroduce the exact
    out-of-budget crash it is meant to survive, and only when the network is
    already down.

    Measured: 1.6s to load, ~292 MiB resident, 1626ms median per capture
    (0.54x realtime). Only good enough for the local rule-tier vocabulary —
    "volume up", "stop" — which is all it has to reach while offline.
    """
    global _cpu_model
    if _cpu_model is None:
        with _cpu_lock:
            if _cpu_model is None:
                from faster_whisper import WhisperModel

                t0 = time.perf_counter()
                _cpu_model = WhisperModel(
                    settings.whisper_model_cpu, device="cpu", compute_type="int8")
                log.warning("offline STT: loaded %s on CPU in %.1fs",
                            settings.whisper_model_cpu, time.perf_counter() - t0)

    # Inference is serialized too, not just the load above. Turn bodies are
    # serialized by wake_word._start_turn — but only up to
    # _TURN_HANDOVER_TIMEOUT_S, and past that several turns run at once and
    # every one of them lands here. One CTranslate2 model configured for all
    # cores, entered by N threads, means N decodes fighting over those cores:
    #
    #     [wake] previous turn still running after 15s; starting anyway
    #     [wake] previous turn still running after 15s; starting anyway
    #     STT: answered offline on CPU in 19120ms   (2995ms earlier that session)
    #
    # The lock spans _collect_segments DELIBERATELY. `transcribe()` returns a
    # lazy generator and does almost nothing itself — faster-whisper decodes
    # while that generator is iterated. Locking only the call would serialize
    # the setup, leave all the real inference concurrent, and read like a
    # correct fix; tests/test_cpu_whisper_is_serialized.py pins both halves.
    with _cpu_lock:
        segments, info = _cpu_model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=_COMMAND_PROMPT,
        )
        return _collect_segments(segments, info)



def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Transcribe a numpy audio array directly — no temp file needed."""
    model = get_model()
    segments, info = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        initial_prompt=_COMMAND_PROMPT,
    )
    return _collect_segments(segments, info)


def transcribe_stream(
    chunk_iterable: Generator[bytes, None, None],
    sample_rate: int = 16000,
) -> dict:
    """Transcribe streaming audio chunks directly — no temp file, no pre-capture.

    Uses silero-vad for accurate endpointing, then passes the clean
    speech segment to faster-whisper for transcription.
    """
    for speech_arr in _filter_speech_chunks(chunk_iterable, sample_rate):
        return transcribe_array(speech_arr, sample_rate)
    return {"text": "", "language": "en", "language_probability": 1.0, "duration_sec": 0.0}


# ── Segment quality gate ────────────────────────────────────────────────
#
# These were one condition: `no_speech_prob > 0.6 or avg_logprob < -1.5`.
# The `or` let no_speech_prob veto on its own, and that silently ate "stop".
#
# Measured over the 30-clip real-voice corpus (36 segments, medium/cuda/fp16):
#
#     no_speech_prob   min 0.098   median 0.282   max 0.616
#     avg_logprob      min -0.868  median -0.460  max -0.293
#
# The single segment the old gate dropped was stop_1 -> 'Stop.', at
# no_speech_prob 0.616 with avg_logprob -0.644. Whisper heard the word and was
# confident about it; it lost by 0.016. One-word utterances score high
# no_speech_prob however clearly they are spoken — stop_2 ("Onyx. Stop.")
# survived at 0.542 only because the wake word made it longer — so every short
# command was exposed and "stop", the abort control, is the shortest.
#
# And no_speech_prob was never the thing guarding against silence: with
# vad_filter=True, three seconds of pure silence yields ZERO segments before
# this code runs. What is left for this gate to catch is confident-sounding
# garbage decoded from noise, and that shows up in BOTH signals at once —
# hence `and`.
#
# _LOW_CONFIDENCE sits below every real-speech observation (worst -0.868) and
# above stop's -0.644, so the combined gate still bites without eating valid
# short commands. _INCOHERENT keeps its independent veto: text that scores
# that badly is not a transcript whatever no_speech_prob says.
_HIGH_NO_SPEECH = 0.6
_LOW_CONFIDENCE = -1.0
_INCOHERENT = -1.5


def _collect_segments(segments, info) -> dict:
    """Filter and collect Whisper segments into a result dict."""
    valid_segments = []
    for seg in segments:
        # Both signals must agree before a segment is discarded.
        if seg.no_speech_prob > _HIGH_NO_SPEECH and seg.avg_logprob < _LOW_CONFIDENCE:
            continue
        if seg.avg_logprob < _INCOHERENT:
            continue

        cleaned = seg.text.strip()
        if cleaned.lower() in ["thank you.", "you", "thanks.", "bye."]:
            if seg.avg_logprob < -0.5:
                continue

        valid_segments.append(cleaned)

    text = " ".join(valid_segments).strip()

    # Whisper reciting its own initial_prompt is not a transcript. It arrives
    # fluent and confident and was dispatched to the router as a command —
    # "play mungaru male music on youtube" came back as the prompt's opening
    # sentence. Dropped to "" so the existing content gate rejects it exactly
    # like any other empty capture.
    if is_prompt_echo(text):
        print(f"[stt] dropped prompt echo: {text!r}")
        text = ""

    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
    }
