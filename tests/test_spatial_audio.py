"""Spatial audio: pan obstacle alerts left/right.

Tests the panning logic and its integration with obstacle detection.

The two speak_panned tests here used to be broken in opposite directions, and
both are worth remembering:

  * one imported speak_panned, then reimplemented the gain arithmetic inline
    and asserted its own copy — it would have passed with speak_panned
    deleted. It also divided per-sample by `np.abs(mono).clip(1)`, so runs
    where synthesis produced more near-silent samples failed at random; that
    was the intermittent red in the suite, not a real regression.
  * the other really did play audio, three times per run, straight to the
    sound card — while this docstring claimed the file did not touch hardware.

Both now drive the REAL speak_panned with the output stream captured, so the
assertions are about the buffer the function actually produces.
"""
import pytest


class _CapturedStream:
    """Stands in for sd.OutputStream and keeps what would have been played."""

    written: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, buffer):
        _CapturedStream.written.append((self.kwargs, buffer))


@pytest.fixture()
def captured_audio(monkeypatch):
    """No sound card, no 3x real playback per run — just the samples."""
    import backend.ai_modules.speech.tts_piper as tts
    _CapturedStream.written = []
    monkeypatch.setattr(tts.sd, "OutputStream", _CapturedStream)
    return _CapturedStream.written


@pytest.mark.parametrize("direction, expect_left, expect_right", [
    ("left", 1.0, 0.25),
    ("right", 0.25, 1.0),
    ("straight", 0.707, 0.707),
])
def test_speak_panned_applies_the_right_channel_gains(captured_audio, direction,
                                                      expect_left, expect_right):
    """Drives the real speak_panned and measures the buffer it emitted.

    Peak amplitude per channel, not a per-sample ratio: silence divided by
    silence is arbitrary, which is what made the old version flaky."""
    import numpy as np
    from backend.ai_modules.speech.tts_piper import speak_panned

    result = speak_panned("test", direction)
    assert result["status"] == "finished", result
    assert captured_audio, "speak_panned never wrote any audio"

    kwargs, buffer = captured_audio[-1]
    assert kwargs["channels"] == 2, f"not stereo: {kwargs}"
    assert buffer.ndim == 2 and buffer.shape[1] == 2, f"shape {buffer.shape}"

    peak_l = float(np.abs(buffer[:, 0]).max())
    peak_r = float(np.abs(buffer[:, 1]).max())
    assert peak_l > 0 and peak_r > 0, "one channel is entirely silent"

    # Compare the CHANNEL BALANCE, which is what panning actually means and is
    # independent of how loud this particular utterance came out.
    assert peak_r / peak_l == pytest.approx(expect_right / expect_left, rel=0.05), (
        f"{direction}: peak L={peak_l:.0f} R={peak_r:.0f} "
        f"(ratio {peak_r / peak_l:.3f}, expected {expect_right / expect_left:.3f})"
    )


def test_speak_panned_reports_the_direction_it_used(captured_audio):
    from backend.ai_modules.speech.tts_piper import speak_panned

    for direction in ("left", "right", "straight"):
        result = speak_panned("test", direction)
        assert result["status"] == "finished", f"Failed for {direction}: {result}"
        assert result["pan"] == direction


def test_a_left_alert_is_louder_on_the_left(captured_audio):
    """The whole point, stated once in plain terms: the ear nearer the hazard
    hears more. A sign flip here would pan every warning the wrong way and be
    invisible to a gains-only assertion."""
    import numpy as np
    from backend.ai_modules.speech.tts_piper import speak_panned

    speak_panned("person on your left", "left")
    _, left_buffer = captured_audio[-1]
    speak_panned("person on your right", "right")
    _, right_buffer = captured_audio[-1]

    assert np.abs(left_buffer[:, 0]).max() > np.abs(left_buffer[:, 1]).max()
    assert np.abs(right_buffer[:, 1]).max() > np.abs(right_buffer[:, 0]).max()


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
