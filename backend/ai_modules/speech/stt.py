"""Which STT engine the voice path uses.

Exists so the Gemini migration is one config flip to revert rather than a
revert commit mid-session. Deleted along with stt_whisper once the live gate
in the design doc's section 7.1 passes — it is scaffolding, not architecture.

Imports both modules eagerly. stt_whisper's import is cheap (the model loads
lazily inside get_model, not at import), so there is no reason to defer it
and every reason not to: a lazy import that fails does so mid-turn.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from backend.ai_modules.speech import stt_gemini, stt_groq, stt_whisper
from backend.server.config import settings

log = logging.getLogger(__name__)

_VALID = ("groq", "gemini", "whisper")


def active_backend() -> str:
    choice = (settings.stt_backend or "groq").strip().lower()
    if choice not in _VALID:
        log.warning("unknown STT_BACKEND %r; using groq", settings.stt_backend)
        return "groq"
    return choice


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    backend = active_backend()
    if backend == "whisper":
        return stt_whisper.transcribe_array(audio, sample_rate)
    if backend == "groq":
        # stt_groq falls back to Gemini internally on any failure, so this is
        # the only place the choice is made.
        return stt_groq.transcribe_array(audio, sample_rate)
    return stt_gemini.transcribe_array(audio, sample_rate)


def transcribe(audio_path: str | Path) -> dict:
    backend = active_backend()
    if backend == "whisper":
        return stt_whisper.transcribe(audio_path)
    if backend == "groq":
        return stt_groq.transcribe(audio_path)
    return stt_gemini.transcribe(audio_path)
