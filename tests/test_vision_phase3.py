"""VisionClaw Phase 3: haptics, silent mode, scan-once.

HapticEvent and OcrReadEvent were both defined in ui_events.py and mapped in
ws_ui.py while never being constructed anywhere — the repo's recurring
"wired but never fired" failure. So the haptic test here watches the vibrate
command arrive over a REAL WebSocket rather than asserting the publish call.
"""
import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.vision import frame_ingest, obstacle_detector as od
from backend.core.vision.frame_ingest import FrameIngestor
from backend.core.vision.phone_session import registry
from backend.server.routes import phone_stream

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(phone_stream.router)
    app.include_router(phone_stream.page_router)
    # High fps cap: the 2fps throttle would drop the second frame, and two
    # accepted frames are required for confirmation.
    fresh = FrameIngestor(max_fps=1000.0)
    orig = frame_ingest.frame_ingestor
    frame_ingest.frame_ingestor = fresh
    phone_stream.frame_ingestor = fresh
    registry._sessions.clear()
    registry._loop = None
    registry.silent = False
    od.detection_runner.reset()
    yield TestClient(app)
    frame_ingest.frame_ingestor = orig
    phone_stream.frame_ingestor = orig
    registry._sessions.clear()
    registry._loop = None
    registry.silent = False
    od.detection_runner.reset()


def _obs(label="person", direction="straight", dist=0.6, prio="critical"):
    return od.Obstacle(label=label, direction=direction, distance_m=dist,
                       confidence=0.9, priority=prio)


def _await_action(ws, action, tries=8):
    for _ in range(tries):
        msg = json.loads(ws.receive_text())
        if msg.get("action") == action:
            return msg
    raise AssertionError(f"no {action!r} command arrived")


def _send_and_settle(ws, runner, timeout=10.0):
    """Send one frame and wait for its detection pass to finish.

    Required for the 2-frame confirmation: submit() skips outright when a
    detection is already in flight, so two frames sent back to back produce
    exactly one detection and nothing is ever confirmed.
    """
    before = runner.detections_done
    ws.send_bytes(JPEG)
    deadline = time.monotonic() + timeout
    while runner.detections_done == before:
        if time.monotonic() > deadline:
            raise AssertionError("detection never ran for the frame just sent")
        time.sleep(0.02)


def test_close_obstacle_vibrates_the_real_phone(client, monkeypatch):
    """The end-to-end proof that HapticEvent stopped being an orphan."""
    monkeypatch.setattr(od, "detect", lambda _b, all_labels=False: [_obs(dist=0.6)])
    monkeypatch.setattr(od.DetectionRunner, "_speak_offloop", lambda self, p: None)

    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_text(json.dumps({"type": "mode_change", "mode": "navigate"}))
        _send_and_settle(ws, od.detection_runner)   # first sighting
        _send_and_settle(ws, od.detection_runner)   # confirms, and is inside 1m
        cmd = _await_action(ws, "vibrate")

    assert cmd["pulses"] == 1  # one long buzz = critical


def test_distant_obstacle_does_not_vibrate(client, monkeypatch):
    """A buzz means 'stop now'. If it fires at 4m it stops meaning anything."""
    monkeypatch.setattr(od, "detect", lambda _b, all_labels=False: [_obs(dist=4.0)])
    spoken = []
    monkeypatch.setattr(od.DetectionRunner, "_speak_offloop",
                        lambda self, p: spoken.append(p))

    runner = od.DetectionRunner()
    buzzed = []
    monkeypatch.setattr(registry, "push_soon", lambda p: buzzed.append(p))

    asyncio.run(runner.submit(b"f1", "navigate"))
    asyncio.run(runner.submit(b"f2", "navigate"))
    assert buzzed == []


def test_silent_mode_keeps_the_buzz_and_drops_the_speech(monkeypatch):
    """Load-bearing safety assertion: silence is about not talking in public,
    not about going unwarned. Removing the haptic too would leave a blind user
    with no alert at all in exactly the crowded place they asked for quiet."""
    monkeypatch.setattr(od, "detect", lambda _b, all_labels=False: [_obs(dist=0.5)])
    spoken, buzzed = [], []
    monkeypatch.setattr(od.DetectionRunner, "_speak_offloop",
                        lambda self, p: spoken.append(p))
    monkeypatch.setattr(registry, "push_soon", lambda p: buzzed.append(p))
    monkeypatch.setattr(registry, "silent", True)

    runner = od.DetectionRunner()
    asyncio.run(runner.submit(b"f1", "navigate"))
    asyncio.run(runner.submit(b"f2", "navigate"))

    assert spoken == [], "silent mode still spoke"
    assert len(buzzed) == 1, "silent mode also removed the haptic warning"


def test_haptic_cooldown_stops_a_buzz_storm(monkeypatch):
    monkeypatch.setattr(od, "detect", lambda _b, all_labels=False: [_obs(dist=0.5)])
    monkeypatch.setattr(od.DetectionRunner, "_speak_offloop", lambda self, p: None)
    buzzed = []
    monkeypatch.setattr(registry, "push_soon", lambda p: buzzed.append(p))

    runner = od.DetectionRunner()
    for _ in range(5):
        asyncio.run(runner.submit(b"f", "navigate"))
    assert len(buzzed) == 1, f"expected one buzz inside the cooldown, got {len(buzzed)}"


def test_describe_groups_and_only_ranges_what_it_can():
    text = od.describe([
        _obs("chair", "left", 0.0, "info"),
        _obs("chair", "left", 0.0, "info"),
        _obs("person", "straight", 3.4, "warning"),
    ])
    assert "2 chairs on your left" in text
    assert "person ahead" in text
    assert "Nearest is the person" in text
    assert "chair, about" not in text  # unknown distance never spoken as a range


def test_describe_empty_is_still_a_sentence():
    assert od.describe([]) == "Nothing recognizable in view."


def test_entering_scan_mode_describes_the_scene_once(client, monkeypatch):
    """Scan is once-triggered by definition — entering the mode is the trigger."""
    monkeypatch.setattr(od, "detect", lambda _b, all_labels=False: [_obs("chair", "left", 0.0, "info")])
    said = []
    monkeypatch.setattr(od.DetectionRunner, "_speak_offloop",
                        lambda self, p: said.append(p))

    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_bytes(JPEG)   # a frame must exist to describe
        ws.send_text(json.dumps({"type": "mode_change", "mode": "scan"}))
        # scan_once runs as a task on the server loop; give it a round trip
        for _ in range(20):
            if said:
                break
            client.get("/vision/phone_frame")

    assert said, "entering scan mode described nothing"
    assert "chair" in said[0]


def test_scan_with_no_frame_says_nothing_rather_than_guessing(client):
    runner = od.DetectionRunner()
    assert asyncio.run(runner.scan_once()) == ""


def test_phone_page_can_vibrate(client):
    page = client.get("/phone").text
    assert "navigator.vibrate" in page
    assert 'd.action === "vibrate"' in page
