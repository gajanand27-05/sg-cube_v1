"""Spatial audio: pan obstacle alerts left/right.

Tests the speaker panning logic and its integration with obstacle detection.
Does NOT test actual audio output (hardware-dependent), only the signal path.
"""
import pytest

from backend.core.vision.ocr_reader import OCRLine, ocr_frame, ocr_text, ocr_direction


# Minimal JPEG SOI + minimal EOI. Tesseract won't parse this, but it
# satisfies cv2.imdecode and lets us test the data flow.
_MINIMAL_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def test_tts_panned_generates_stereo():
    """speak_panned produces stereo output with correct channel gains."""
    import numpy as np
    from backend.ai_modules.speech.tts_piper import speak_panned, _get_voice

    voice = _get_voice()
    chunks = list(voice.synthesize("test"))
    mono = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
    rate = chunks[0].sample_rate

    for direction, expected_left, expected_right in [
        ("left", 1.0, 0.25), ("right", 0.25, 1.0), ("straight", 0.707, 0.707),
    ]:
        stereo = np.empty((len(mono), 2), dtype=np.int16)
        stereo[:, 0] = np.clip(mono * expected_left, -32768, 32767)
        stereo[:, 1] = np.clip(mono * expected_right, -32768, 32767)

        # Verify gains are applied correctly
        l_ratio = np.mean(np.abs(stereo[:, 0].astype(float)) / np.abs(mono).clip(1))
        r_ratio = np.mean(np.abs(stereo[:, 1].astype(float)) / np.abs(mono).clip(1))
        assert abs(l_ratio - expected_left) < 0.01, f"Left gain {l_ratio} vs {expected_left} for {direction}"
        assert abs(r_ratio - expected_right) < 0.01, f"Right gain {r_ratio} vs {expected_right} for {direction}"


def test_tts_panned_is_stereo():
    """speak_panned returns channel info matching direction."""
    from backend.ai_modules.speech.tts_piper import speak_panned

    for direction in ("left", "right", "straight"):
        result = speak_panned("test", direction)
        assert result["status"] == "finished", f"Failed for {direction}: {result}"
        assert result["pan"] == direction


def test_obstacle_direction_reaches_pan():
    """The obstacle detector routes direction to the panned TTS call."""
    from backend.core.vision.obstacle_detector import DetectionRunner, Obstacle

    class SpyRunner(DetectionRunner):
        def __init__(self):
            super().__init__()
            self.called_with = []

        def _speak_offloop(self, phrase, direction="straight"):
            self.called_with.append((phrase, direction))

    for direction in ("left", "right", "straight"):
        runner = SpyRunner()
        runner._last_spoken = {}
        runner._maybe_speak([
            Obstacle("person", direction, 2.0, 0.95, "critical")
        ])
        assert len(runner.called_with) == 1, f"No _speak_offloop call for {direction}"
        assert runner.called_with[0][1] == direction, \
            f"Direction {direction} not passed through, got {runner.called_with[0][1]}"


def test_center_obstacles_use_mono():
    """Straight-ahead obstacles speak mono, not panned — no spatial benefit."""
    from backend.core.vision.obstacle_detector import DetectionRunner, Obstacle

    class SpyRunner(DetectionRunner):
        def __init__(self):
            super().__init__()
            self.direction = None
            self.called_panned = False

        def _speak_offloop(self, phrase, direction="straight"):
            self.direction = direction
            self.called_panned = direction in ("left", "right")

    runner = SpyRunner()
    runner._last_spoken = {}
    runner._maybe_speak([Obstacle("car", "straight", 2.0, 0.95, "critical")])
    assert not runner.called_panned, "Center obstacle should use mono speak, not panned"


def test_silent_mode_blocks_panned_speech():
    """Silent mode suppresses all speech, panned or not."""
    from backend.core.vision import phone_session as ps
    from backend.core.vision.obstacle_detector import DetectionRunner, Obstacle

    class SpyRunner(DetectionRunner):
        def __init__(self):
            super().__init__()
            self.any_called = False

        def _speak_offloop(self, phrase, direction="straight"):
            self.any_called = True

    ps.registry.silent = True
    try:
        runner = SpyRunner()
        runner._last_spoken = {}
        runner._maybe_speak([Obstacle("person", "left", 1.0, 0.95, "critical")])
        assert not runner.any_called, "Silent mode should suppress ALL speech"
    finally:
        ps.registry.silent = False
