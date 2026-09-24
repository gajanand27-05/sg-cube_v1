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

FAILS OPEN. If the VAD will not load, every capture passes. A broken VAD
must never be able to silence the assistant.

The model is faster-whisper's bundled Silero v5 (ONNX, onnxruntime + numpy),
not the `silero-vad` pip package: that package imports torch at module level
even for its ONNX path, and torch was ~524 MB of install for this one call.
Swapped 2026-09-24 after measuring both on 374 real clips that reach this gate
(archived captures + the STT corpus), with the parameters below:

    decision flips          3 at min_speech=250ms, 1 at 150ms
    real commands dropped   none newly (the one flip at 150ms is a follow-up
                            whose whole transcript was the wake word 'onyx')
    empty-transcript kept   68 old vs 67 new (noise filtering unchanged)
    per clip                186ms old vs 53ms new

min_speech is 150ms, not silero's 250ms default, on measurement: v5 finds
shorter segments on the shortest commands, and at 250ms 'stop' (stop_1)
scored 0.32s — ~10ms above being discarded outright. At 150ms it scores
0.57s, and 'Onyx open notepad' keeps a larger margin than it had before.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

_model = None
_load_failed = False
_lock = threading.Lock()


def _vad_options():
    from faster_whisper.vad import VadOptions

    # silero-vad's own defaults as this gate used to call it (offset is its
    # implicit threshold - 0.15), except min_speech — see the module docstring.
    return VadOptions(onset=0.5, offset=0.35, min_speech_duration_ms=150,
                      max_speech_duration_s=float("inf"),
                      min_silence_duration_ms=100, speech_pad_ms=30)


def _speech_timestamps(audio: np.ndarray, sample_rate: int) -> list[dict]:
    """Speech segments in SAMPLES. Its own function so tests can make it raise."""
    from faster_whisper.vad import get_speech_timestamps

    return get_speech_timestamps(audio, _vad_options(), sampling_rate=sample_rate)


def _get_model():
    """Lazy-load the VAD once. None (latched) when it cannot load."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from faster_whisper.vad import get_vad_model

            # lru_cached inside faster-whisper, so _speech_timestamps reuses it.
            _model = get_vad_model()
            log.info("speech gate: silero v5 (onnx) loaded")
        except Exception as e:
            _load_failed = True
            log.warning("speech gate: VAD unavailable (%s); "
                        "every capture will pass through", e)
    return _model


def speech_seconds(audio: np.ndarray, sample_rate: int = 16000) -> float | None:
    """Seconds of detected speech, or None when the VAD is unavailable.

    None and 0.0 mean very different things — "could not measure" versus
    "measured, found nothing" — so they must not collapse into one value.
    """
    if _get_model() is None:
        return None
    try:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr[:, 0]
        if arr.size == 0:
            return 0.0
        stamps = _speech_timestamps(arr, sample_rate)
        return float(sum(s["end"] - s["start"] for s in stamps)) / sample_rate
    except Exception as e:
        log.warning("speech gate: VAD failed mid-call (%s); passing through", e)
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
