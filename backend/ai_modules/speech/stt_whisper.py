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
    model = get_model()
    segments, info = model.transcribe(str(audio_path), beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
    }
