"""VisionClaw Phase 2: YOLO obstacle detection.

Real-model tests use ultralytics' bundled bus.jpg (4 persons + 1 bus in COCO
ground truth); the first run downloads yolov8n.pt (~6MB) once. Runner logic
(2-frame confirmation, busy-skip, cooldown) is tested with detect() stubbed.
"""
import asyncio
from pathlib import Path

import pytest

from backend.core.vision import obstacle_detector as od

BUS_JPG = Path(__file__).parents[1] / ".venv/Lib/site-packages/ultralytics/assets/bus.jpg"


@pytest.fixture(scope="module")
def bus_bytes():
    if not BUS_JPG.exists():
        pytest.skip("ultralytics assets not found")
    return BUS_JPG.read_bytes()


def test_detect_finds_people_and_bus(bus_bytes):
    obstacles = od.detect(bus_bytes)
    labels = {o.label for o in obstacles}
    assert "person" in labels and "bus" in labels
    for o in obstacles:
        assert o.direction in ("left", "straight", "right")
        assert 0.3 < o.distance_m < 60, f"{o.label} distance {o.distance_m} implausible"
        assert o.confidence >= od.MODEL_CONF
        assert o.priority in ("critical", "warning")


def test_detect_garbage_bytes_yield_nothing():
    assert od.detect(b"not a jpeg") == []


def _obs(label="person", direction="straight", dist=1.5, prio="critical"):
    return od.Obstacle(label=label, direction=direction, distance_m=dist,
                       confidence=0.9, priority=prio)


def test_runner_two_frame_confirmation(monkeypatch):
    published = []
    runner = od.DetectionRunner()
    monkeypatch.setattr(od, "detect", lambda _b: [_obs()])
    monkeypatch.setattr(od.DetectionRunner, "_maybe_speak", lambda self, c: None)

    class Bus:
        def publish(self, ev, priority=None):
            published.append(ev)
    monkeypatch.setattr(od, "get_bus", lambda: Bus())

    asyncio.run(runner.submit(b"f1", "navigate"))
    assert published == []  # first sighting: not yet confirmed
    asyncio.run(runner.submit(b"f2", "navigate"))
    assert len(published) == 1 and published[0].label == "person"


def test_runner_skips_outside_detection_modes(monkeypatch):
    runner = od.DetectionRunner()
    monkeypatch.setattr(od, "detect", lambda _b: (_ for _ in ()).throw(AssertionError("must not run")))
    asyncio.run(runner.submit(b"f", "idle"))
    asyncio.run(runner.submit(b"f", "read"))


def _flush_speech_pool():
    """Alerts are dispatched to a single-worker pool, so a task queued behind
    them is done only once they are."""
    od._speech_pool.submit(lambda: None).result(timeout=10)


def test_speak_cooldown(monkeypatch):
    spoken = []
    runner = od.DetectionRunner()
    import backend.ai_modules.speech.tts_piper as tts
    monkeypatch.setattr(tts, "speak", lambda text: spoken.append(text))
    runner._maybe_speak([_obs(dist=2.0)])
    runner._maybe_speak([_obs(dist=1.0)])  # same label, inside cooldown
    _flush_speech_pool()
    assert len(spoken) == 1
    assert "person" in spoken[0] and "ahead" in spoken[0]


def test_alert_never_speaks_on_the_callers_event_loop(monkeypatch):
    """tts_piper.speak() branches on asyncio.get_running_loop(): with a loop it
    schedules playback there, and playback blocks for the length of the audio.
    submit() runs on the uvicorn loop, so speaking inline would stall the HTTP
    server and both WebSockets on every alert.

    Asserting 'speak was called' passes with the bug present — the load-bearing
    assertion is which loop the call lands on.
    """
    seen = {}
    import backend.ai_modules.speech.tts_piper as tts

    def fake_speak(text):
        try:
            seen["loop"] = asyncio.get_running_loop()
        except RuntimeError:
            seen["loop"] = None  # what we want: speak() takes its own-loop path
        seen["text"] = text

    monkeypatch.setattr(tts, "speak", fake_speak)
    monkeypatch.setattr(od, "detect", lambda _b: [_obs()])

    class Bus:
        def publish(self, ev, priority=None):
            pass
    monkeypatch.setattr(od, "get_bus", lambda: Bus())

    runner = od.DetectionRunner()

    async def two_frames():
        await runner.submit(b"f1", "navigate")
        await runner.submit(b"f2", "navigate")  # second sighting confirms + speaks
        return asyncio.get_running_loop()

    caller_loop = asyncio.run(two_frames())
    _flush_speech_pool()

    assert seen.get("text"), "the confirmed critical obstacle was never spoken"
    assert seen["loop"] is None, (
        f"speak() ran with a live event loop ({seen['loop']!r}) — playback would "
        "block that loop; it must run on a thread with no loop of its own"
    )
    assert seen["loop"] is not caller_loop
