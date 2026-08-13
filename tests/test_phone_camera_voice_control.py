"""Voice-driven phone camera: server -> phone control channel.

The load-bearing tests here drive a REAL WebSocket via TestClient and run the
tool on a REAL foreign event loop (`asyncio.run` in a worker thread, which is
what the daemon's per-capture handle_wake does). Mocking the socket would prove
the tool's branching and nothing about delivery — and delivery across a loop
boundary is the part that actually breaks.
"""
import asyncio
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.vision import frame_ingest
from backend.core.vision.frame_ingest import FrameIngestor
from backend.core.vision.phone_session import registry
from backend.core.tools.vision_phone import (
    connect_phone_camera,
    describe_scene,
    disconnect_phone_camera,
    ocr_read,
)
from backend.server.routes import phone_stream

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(phone_stream.router)
    app.include_router(phone_stream.page_router)
    fresh = FrameIngestor(max_fps=2.0)
    orig = frame_ingest.frame_ingestor
    frame_ingest.frame_ingestor = fresh
    phone_stream.frame_ingestor = fresh
    registry._sessions.clear()
    registry._loop = None
    yield TestClient(app)
    frame_ingest.frame_ingestor = orig
    phone_stream.frame_ingestor = orig
    registry._sessions.clear()
    registry._loop = None


def _call_tool_on_foreign_loop(coro_factory, out: dict):
    """Run a tool the way a spoken turn does: its own fresh event loop, on a
    different thread from the one owning the phone socket."""
    def runner():
        try:
            out["result"] = asyncio.run(coro_factory())
        except Exception as e:  # surface it instead of hanging the join
            out["error"] = e
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def _next_command(ws, tries: int = 5) -> dict:
    """Read past the periodic health frame to the pushed command."""
    for _ in range(tries):
        msg = json.loads(ws.receive_text())
        if msg.get("type") == "command":
            return msg
    raise AssertionError("no command frame arrived from the server")


def test_connect_tool_starts_camera_over_the_real_socket(client):
    """The whole point: a tool call on a foreign loop reaches the phone."""
    with client.websocket_connect("/ws/phone_stream") as ws:
        out: dict = {}
        t = _call_tool_on_foreign_loop(lambda: connect_phone_camera(mode="navigate"), out)

        cmd = _next_command(ws)
        assert cmd["action"] == "start"
        assert cmd["mode"] == "navigate"

        # The phone confirms it actually opened the camera.
        ws.send_text(json.dumps({"type": "status", "streaming": True, "mode": "navigate"}))
        t.join(timeout=15)

    assert "error" not in out, out.get("error")
    res = out["result"]
    assert res.status.value == "success", res.message or res.reason
    assert res.data["streaming"] is True


def test_camera_failure_on_the_phone_is_not_reported_as_success(client):
    """Delivery is not the same as the camera working. A denied permission must
    come back as an error, or the user is told a dead camera is live."""
    with client.websocket_connect("/ws/phone_stream") as ws:
        out: dict = {}
        t = _call_tool_on_foreign_loop(lambda: connect_phone_camera(), out)

        assert _next_command(ws)["action"] == "start"
        ws.send_text(json.dumps({
            "type": "status", "streaming": False,
            "error": "camera permission denied — tap Start Streaming on the phone once",
        }))
        t.join(timeout=15)

    res = out["result"]
    assert res.status.value != "success"
    assert "permission denied" in (res.reason or res.message or "")


def test_no_phone_connected_reports_how_to_pair(client):
    res = asyncio.run(connect_phone_camera())
    assert res.status.value != "success"
    assert "no phone connected" in (res.reason or "")


def test_unknown_mode_rejected_without_touching_the_phone(client):
    res = asyncio.run(connect_phone_camera(mode="teleport"))
    assert res.status.value != "success"
    assert "teleport" in (res.reason or "")


def test_disconnect_stops_the_camera(client):
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_bytes(JPEG)  # session is streaming
        out: dict = {}
        t = _call_tool_on_foreign_loop(disconnect_phone_camera, out)
        assert _next_command(ws)["action"] == "stop"
        ws.send_text(json.dumps({"type": "status", "streaming": False}))
        t.join(timeout=15)

    res = out["result"]
    assert res.status.value == "success", res.reason


def test_disconnect_with_no_phone_is_not_an_error(client):
    res = asyncio.run(disconnect_phone_camera())
    assert res.status.value == "success"


def test_stale_frame_is_dropped_when_the_phone_goes_away(client):
    """A frozen image served with HTTP 200 reads as a live feed. For a
    navigation aid that is the worst possible failure, so disconnect must
    return the HUD to 'no feed'."""
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_bytes(JPEG)
    assert client.get("/vision/phone_frame").status_code == 404


def test_describe_scene_without_a_frame_says_how_to_start(client):
    res = asyncio.run(describe_scene())
    assert res.status.value != "success"
    assert "no camera frame" in (res.reason or "")


def test_describe_scene_groups_and_ranges(client, monkeypatch):
    from backend.core.vision import obstacle_detector as od

    def fake_detect(_jpeg, all_labels=False):
        assert all_labels, "scene description must not drop non-obstacle classes"
        return [
            od.Obstacle("chair", "left", 0.0, 0.9, "info"),
            od.Obstacle("chair", "left", 0.0, 0.8, "info"),
            od.Obstacle("person", "straight", 3.2, 0.9, "warning"),
        ]

    monkeypatch.setattr(od, "detect", fake_detect)
    frame_ingest.frame_ingestor.ingest_frame(JPEG, mode="scan")

    res = asyncio.run(describe_scene())
    assert res.status.value == "success", res.reason
    assert "2 chairs on your left" in res.message
    assert "person ahead" in res.message
    # Only the ranged object may be called out by distance; the 0.0 "unknown"
    # rows must never be reported as being at the user's feet.
    assert "Nearest is the person" in res.message
    assert len(res.data["objects"]) == 3


def test_all_labels_keeps_classes_that_have_no_known_height(monkeypatch):
    """The default filter drops everything without a height, so 'what do you
    see' would only ever name the 12 obstacle classes without this."""
    from pathlib import Path
    from backend.core.vision import obstacle_detector as od

    asset = Path(__file__).parents[1] / ".venv/Lib/site-packages/ultralytics/assets/zidane.jpg"
    if not asset.exists():
        pytest.skip("ultralytics assets not found")
    monkeypatch.setattr(od, "MODEL_CONF", 0.25)  # surface the low-confidence tie
    jpeg = asset.read_bytes()

    only = {o.label for o in od.detect(jpeg)}
    every = {o.label for o in od.detect(jpeg, all_labels=True)}
    extra = every - only
    assert extra, "all_labels returned nothing the default filter did not"
    assert extra.isdisjoint(od.KNOWN_HEIGHTS)
    for o in od.detect(jpeg, all_labels=True):
        if o.label not in od.KNOWN_HEIGHTS:
            assert o.distance_m == 0.0 and o.priority == "info"


def test_page_opens_its_control_socket_on_load(client):
    """If the page only connected while streaming, there would be nothing to
    send 'start' to — the feature would be impossible."""
    page = client.get("/phone").text
    assert page.rstrip().endswith("</html>")
    # connect() is invoked at top level, not only from start()
    assert "\nconnect();" in page
    assert '"command"' in page and 'd.action === "start"' in page


def test_ocr_read_without_frame(client):
    res = asyncio.run(ocr_read())
    assert res.status.value != "success"
    assert "no camera frame" in (res.reason or "")


def test_ocr_read_groups_lines(client, monkeypatch):
    from backend.core.vision import ocr_reader as orr

    def fake_ocr(_jpeg):
        return [
            orr.OCRLine(text="STOP", bbox=(0, 0, 100, 20), confidence=0.95),
            orr.OCRLine(text="MAIN ST", bbox=(0, 30, 100, 50), confidence=0.88),
        ]

    monkeypatch.setattr(orr, "ocr_frame", fake_ocr)
    frame_ingest.frame_ingestor.ingest_frame(JPEG, mode="read")

    res = asyncio.run(ocr_read())
    assert res.status.value == "success", res.reason
    assert "STOP" in res.message
    assert "MAIN ST" in res.message
    assert len(res.data["lines"]) == 2


def test_switch_to_read_mode(client):
    """Phone should receive mode change command."""
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_bytes(JPEG)
        ws.send_text(json.dumps({"type": "mode_change", "mode": "read"}))
        # time_sync arrives first on connect, skip past it
        json.loads(ws.receive_text())


def test_read_mode_continuous_ocr(client, monkeypatch):
    """Read mode should run OCR on frames, not skip like navigate/scan/idle."""
    from backend.core.vision import ocr_reader as _ocr_mod
    from backend.core.vision.obstacle_detector import detection_runner
    import asyncio

    # Force _busy off so the frame isn't skipped
    detection_runner._busy = False
    detection_runner._last_read_spoken.clear()

    occurrences: list[str] = []

    def fake_ocr(_jpeg):
        occurrences.append("called")
        return [_ocr_mod.OCRLine(text="TEST_LINE", bbox=(0, 0, 10, 10), confidence=0.9)]

    monkeypatch.setattr("backend.core.vision.ocr_reader.ocr_frame", fake_ocr)

    # Run read_once directly on the test loop — this isolates the logic from
    # WS timing and async scheduling complexity.
    frame_ingest.frame_ingestor.ingest_frame(JPEG, mode="read")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(detection_runner.read_once())
    loop.close()

    assert "TEST_LINE" in result
    assert "called" in occurrences
