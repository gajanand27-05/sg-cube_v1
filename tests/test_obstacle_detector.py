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


# ── close-range geometry ─────────────────────────────────────────────
#
# The haptic alert was dead in production for 6 of 7 hazard classes. Not a
# wiring bug: distance = H * frame_h / box_h and box_h <= frame_h, so the
# smallest distance the model can report is H itself — 1.70m for a person,
# with HAPTIC_DISTANCE_M at 1.0. Only the dog (0.50) could ever buzz.
#
# These go through the real detect() on a real image, because the previous
# test for this built an Obstacle by hand and so passed with the bug present.

@pytest.fixture(scope="module")
def person_filling_frame(bus_bytes):
    """A crop of bus.jpg where the pedestrian runs off both the top and the
    bottom edge — what the camera actually sees when someone is within arm's
    reach."""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(bus_bytes, np.uint8), cv2.IMREAD_COLOR)
    ok, enc = cv2.imencode(".jpg", img[420:880, 30:270])  # person box is [49,399,245,903]
    assert ok
    return enc.tobytes()


def test_person_too_close_to_fit_in_frame_is_not_reported_as_far_away(person_filling_frame):
    people = [o for o in od.detect(person_filling_frame) if o.label == "person"]
    assert people, "the crop must still detect a person, or this test proves nothing"
    near = min(people, key=lambda o: o.distance_m)
    assert near.clipped, "bbox runs off both frame edges — detect() must notice"
    assert near.distance_m < od.HAPTIC_DISTANCE_M, (
        f"person filling the frame reported at {near.distance_m}m; the pinhole "
        f"estimate saturates at its own height (1.70m) and never reaches the "
        f"{od.HAPTIC_DISTANCE_M}m haptic threshold"
    )
    assert near.priority == "critical"


def test_haptic_fires_for_a_person_at_arms_length(person_filling_frame, monkeypatch):
    """End of the chain: detection -> _maybe_buzz -> HapticEvent + phone push.
    This is the assertion that was false in production."""
    events, pushes = [], []

    class Bus:
        def publish(self, ev, priority=None):
            events.append(ev)
    monkeypatch.setattr(od, "get_bus", lambda: Bus())
    monkeypatch.setattr(od.registry, "push_soon", lambda payload: pushes.append(payload))

    od.DetectionRunner()._maybe_buzz(od.detect(person_filling_frame))

    assert [e for e in events if isinstance(e, od.HapticEvent)], "no buzz for a person at arm's length"
    assert pushes and pushes[0]["action"] == "vibrate"


def test_unclipped_detections_keep_their_measured_distance(bus_bytes):
    """The fix must not flatten every distance to the close-range constant —
    the uncropped frame's pedestrians are metres away and stay that way."""
    for o in od.detect(bus_bytes):
        assert not o.clipped
        assert o.distance_m > od.CLIPPED_DISTANCE_M


def test_clipped_obstacle_is_spoken_as_very_close_not_as_a_measurement():
    """CLIPPED_DISTANCE_M is a stand-in for 'closer than measurable'. Speaking
    it as '1 meters' would state a precision the geometry cannot support."""
    clipped = od.Obstacle(label="person", direction="straight",
                          distance_m=od.CLIPPED_DISTANCE_M, confidence=0.9,
                          priority="critical", clipped=True)
    assert "very close" in od.describe([clipped]).lower()

    spoken = []
    runner = od.DetectionRunner()
    runner._speak_offloop = lambda phrase, direction="straight": spoken.append(phrase)
    runner._maybe_speak([clipped])
    assert spoken and "very close" in spoken[0].lower(), spoken
    assert "meters" not in spoken[0].lower()


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
