"""Is there any speech in this capture at all?

Runs between the wake word and STT. The wake word fires on sound; this asks
whether a human actually said something, and drops the capture if not.

Measured on 41 archived September captures, 26 of which produced an empty
transcript in production:

    group        n    speech-ratio min / median / max
    NOISE       21    0.000 / 0.465 / 0.876
    DISPATCHED  15    0.000 / 0.512 / 0.941

Those distributions OVERLAP, which is why this gate is deliberately set at
"silero found literally zero speech" and not at a ratio. The real command
'Onyx open notepad' contains only 0.40s of speech — less than most of the
noise clips — so any proportional threshold eats commands before it eats
noise. At zero the gate drops 6 of 21 noise captures and no real command.

It is a 29% cut, not a fix. Most of what the wake word lets through is
ambient human conversation, which is speech by every measure silero has; no
VAD can separate "spoken to Onyx" from "spoken near Onyx". Only the wake
word can, and that is a separate job.

FAILS OPEN. If silero will not load, every capture passes. A broken VAD
must never be able to silence the assistant.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

_model = None
_load_failed = False
_lock = threading.Lock()


def _get_model():
    """Lazy-load silero from the PIP PACKAGE, not torch.hub.

    torch.hub.load("snakers4/silero-vad") prompts for repo trust on a machine
    that has not whitelisted it and then raises — which is why the first
    attempt to use this returned -1 for every clip. The `silero-vad` pip
    package is already a declared dependency and needs no download.
    """
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from silero_vad import load_silero_vad

            _model = load_silero_vad(onnx=False)
            log.info("speech gate: silero-vad loaded")
        except Exception as e:
            _load_failed = True
            log.warning("speech gate: silero unavailable (%s); "
                        "every capture will pass through", e)
    return _model


def speech_seconds(audio: np.ndarray, sample_rate: int = 16000) -> float | None:
    """Seconds of detected speech, or None when the VAD is unavailable.

    None and 0.0 mean very different things — "could not measure" versus
    "measured, found nothing" — so they must not collapse into one value.
    """
    model = _get_model()
    if model is None:
        return None
    try:
        import torch
        from silero_vad import get_speech_timestamps

        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr[:, 0]
        if arr.size == 0:
            return 0.0
        stamps = get_speech_timestamps(
            torch.from_numpy(arr), model,
            sampling_rate=sample_rate, return_seconds=True,
        )
        return float(sum(s["end"] - s["start"] for s in stamps))
    except Exception as e:
        log.warning("speech gate: silero failed mid-call (%s); passing through", e)
        return None


def has_speech(audio: np.ndarray, sample_rate: int = 16000) -> tuple[bool, float | None]:
    """(keep_this_capture, speech_seconds).

    keep is True whenever the gate is disabled, the VAD is unavailable, or any
    speech at all was found — every uncertain case passes.
    """
    from backend.server.config import settings

    if not getattr(settings, "enable_speech_gate", True):
        return True, None
    secs = speech_seconds(audio, sample_rate)
    if secs is None:
        return True, None
    threshold = float(getattr(settings, "speech_gate_min_seconds", 0.0))
    return (secs > threshold), secs
