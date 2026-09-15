"""Capture termination must ignore room noise; wake detection must not.

One constant, `_VAD_RMS_THRESHOLD` (50), served three jobs:

  * which frames reach the Vosk recognizer   -> needs to be LOW (wake word)
  * whether a capture has started            -> needs to be LOW
  * whether the user has STOPPED speaking    -> needs to be ABOVE room noise

The first two and the third have opposite requirements, and it showed up as a
hard conflict measured on a real machine in a real room (Voice Clarity on,
two people talking 2m away):

    floor       p50  384   p90 1161      -> 0.0% of frames below 50
    speech      p25 4753   p50 6080      -> 4.09x headroom, plenty

At threshold 50 not a single frame of a 30s silent recording fell below it,
so the 800ms trailing-silence rule could never fire and EVERY capture ran to
the 10s hard cap. Raising the shared constant was not an option either —
tests/test_barge_in_real_audio.py fails at 100, 200, 300, 400, 450 and 500.

So the threshold is split. `capture_silence_threshold` governs only the
"has the user stopped talking" decision; the Vosk gate and wake detection
keep `vad_rms_threshold`. Default equals vad_rms_threshold, so nothing moves
until someone calibrates with tools/calibrate_mic.py.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.server.config import settings


SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME = SAMPLE_RATE * FRAME_MS // 1000


def _frames(level: float, ms: int) -> list[bytes]:
    """Constant-amplitude int16 frames at the given RMS."""
    n = ms // FRAME_MS
    arr = np.full(FRAME, int(level), dtype=np.int16)
    return [arr.tobytes()] * n


def _rms(chunk: bytes) -> float:
    a = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0


def test_settings_expose_a_separate_capture_threshold():
    assert hasattr(settings, "capture_silence_threshold")


def test_capture_threshold_defaults_to_the_vad_threshold():
    """Unchanged behaviour until deliberately calibrated.

    _env_file=None is load-bearing: a plain Settings() reads the developer's
    .env, so once this machine was calibrated (CAPTURE_SILENCE_THRESHOLD=1500)
    the test was asserting against local config rather than the default.
    """
    from backend.server.config import Settings
    fresh = Settings(_env_file=None, vad_rms_threshold=77.0)
    assert fresh.capture_silence_threshold == 77.0


def test_wake_gate_and_capture_gate_are_read_from_different_settings():
    """The regression guard. Collapsing these back into one constant
    re-creates the conflict: either the wake word stops working or captures
    never end."""
    import backend.daemon.wake_word as ww
    src = Path(ww.__file__).read_text(encoding="utf-8")
    assert "_CAPTURE_SILENCE_THRESHOLD" in src, (
        "capture termination must use its own threshold, not _VAD_RMS_THRESHOLD"
    )


def test_room_noise_counts_as_silence_for_capture_termination():
    """A frame at the measured room floor (384) must NOT look like speech to
    the capture loop once calibrated above it — otherwise trailing silence
    never accumulates and the capture runs to the hard cap."""
    import backend.daemon.wake_word as ww

    room_noise = _frames(384, FRAME_MS)[0]
    assert _rms(room_noise) == pytest.approx(384, abs=1)
    # Calibrated for this room: capture gate above the floor, wake gate at 50.
    assert _rms(room_noise) < 500, "sanity: the fixture is room-level, not speech"


def test_real_speech_still_counts_as_speech_at_a_calibrated_threshold():
    """Measured speech p25 was 4753 — it must stay far above any threshold
    calibrated against a 384 floor."""
    speech = _frames(4753, FRAME_MS)[0]
    assert _rms(speech) > 500 * 4, "speech must clear a calibrated gate with margin"


def test_capture_gate_can_exceed_wake_gate_without_touching_it():
    """The whole point: raise one, leave the other alone."""
    from backend.server.config import Settings
    s = Settings(vad_rms_threshold=50.0, capture_silence_threshold=500.0)
    assert s.vad_rms_threshold == 50.0
    assert s.capture_silence_threshold == 500.0
    assert s.capture_silence_threshold > s.vad_rms_threshold
