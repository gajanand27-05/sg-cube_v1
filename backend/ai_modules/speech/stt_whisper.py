from functools import lru_cache
from pathlib import Path

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


def transcribe(audio_path: str | Path) -> dict:
    """Transcribe a short voice-command clip.

    Tuned for ~2s English command audio:
      - language="en" — skip Whisper's language-detect pass (~200ms saved,
        avoids occasional misidentification on noisy short clips).
      - beam_size=1 — greedy decoding. Beam search helps with long-form
        audio; for 1-3 word commands it's strictly slower with no gain.
      - vad_filter=True — drop silence/noise around the spoken bit so the
        decoder only sees the audio that matters. Big speedup when the user
        speaks for <1s inside a 2.5s capture window.
    """
    model = get_model()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
    }
