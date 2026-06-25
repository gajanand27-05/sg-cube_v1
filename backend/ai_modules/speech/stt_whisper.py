from functools import lru_cache
from pathlib import Path
from typing import Generator

import numpy as np
from faster_whisper import WhisperModel

from backend.server.config import settings


@lru_cache(maxsize=1)
def get_model() -> WhisperModel:
    """Load Whisper once, cache for the process lifetime.

    Defaults: CPU + int8 — works on any machine without CUDA.
    Switch to device='cuda' + compute_type='float16' if you have a GPU.
    First call downloads the model weights (~140MB for 'base').
    """
    return WhisperModel(
        settings.whisper_model,
        device="cpu",
        compute_type="int8",
    )


# Initial-prompt biasing for Whisper. Single-word commands ("lock",
# "next", "stop") often get rewritten to common everyday words ("luck",
# "neck") because they have no context. The prompt below is prose-style
# (NOT a comma-separated list — comma lists teach Whisper to split words
# like "notepad" into "note, pad"). Reads as if a previous user just
# spoke similar commands, which is how Whisper's prompt mechanism is
# designed to work.
_COMMAND_PROMPT = (
    "I am using a voice assistant. I say things like open notepad, "
    "close chrome, lock the screen, play music on youtube, search google, "
    "what time is it, whats the weather, read the news, set a reminder, "
    "translate this to spanish, summarize this article. The assistant "
    "controls notepad, chrome, firefox, vscode, spotify, whatsapp, "
    "discord, telegram, calculator, explorer, and other apps."
)

# ── Phase C1: silero-vad integration ──
_SILERO_VAD = None


def _get_silero_vad():
    global _SILERO_VAD
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


def _collect_segments(segments, info) -> dict:
    """Filter and collect Whisper segments into a result dict."""
    valid_segments = []
    for seg in segments:
        if seg.no_speech_prob > 0.6 or seg.avg_logprob < -1.5:
            continue

        cleaned = seg.text.strip()
        if cleaned.lower() in ["thank you.", "you", "thanks.", "bye."]:
            if seg.avg_logprob < -0.5:
                continue

        valid_segments.append(cleaned)

    text = " ".join(valid_segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
    }
