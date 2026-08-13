"""Read mode, whole chain, no mocks in the middle.

Every hop below has been tested in isolation and every hop has been broken at
some point this session. What none of those tests covered is the chain itself:

  phone WS  ->  frame_ingestor  ->  detection_runner.submit(mode="read")
            ->  ocr_frame (REAL Tesseract)  ->  OcrReadEvent
            ->  bus  ->  ws_ui bridge  ->  /ws/ui  ->  HUD

The pieces passing individually is exactly the state this repo keeps shipping
in: the router that was imported but never mounted, the event with no
publisher, the coroutine never awaited. So this drives two REAL WebSockets
against a REAL running bus and a REAL OCR engine, sends an actual JPEG of an
actual sign, and reads the text back off the HUD socket.

The camera itself is the one hop still unproven — that needs the physical
phone.
"""
import json
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.events import init_event_bus
from backend.core.vision import frame_ingest, obstacle_detector
from backend.core.vision.frame_ingest import FrameIngestor
from backend.core.vision.ocr_reader import tesseract_path
from backend.core.vision.phone_session import registry
from backend.server.routes import phone_stream, ui as ui_route

pytestmark = pytest.mark.skipif(tesseract_path() is None,
                                reason="Tesseract binary not installed")

LOOPBACK = ("127.0.0.1", 4000)
RECEIVE_TIMEOUT_S = 20.0


def _sign_jpeg(text: str) -> bytes:
    """A real photo-shaped JPEG of a sign — this is what the phone sends."""
    import cv2
    import numpy as np
    img = np.full((240, 800, 3), 255, np.uint8)
    cv2.putText(img, text, (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 5)
    return cv2.imencode(".jpg", img)[1].tobytes()


@pytest.fixture()
def app_client(monkeypatch):
    @asynccontextmanager
    async def lifespan(_app):
        bus = init_event_bus()
        await bus.start()
        yield
        await bus.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(phone_stream.router)
    app.include_router(ui_route.router)

    fresh = FrameIngestor(max_fps=2.0)
    monkeypatch.setattr(frame_ingest, "frame_ingestor", fresh)
    monkeypatch.setattr(phone_stream, "frame_ingestor", fresh)

    # Capture speech instead of playing it — a real utterance would block the
    # single-worker TTS pool and hit a sound card that may not exist.
    spoken: list[str] = []
    monkeypatch.setattr(obstacle_detector.DetectionRunner, "_speak_offloop",
                        lambda self, phrase, direction="straight": spoken.append(phrase))

    obstacle_detector.detection_runner.reset()
    registry._sessions.clear()
    registry._loop = None
    with TestClient(app, client=LOOPBACK) as client:
        yield client, spoken
    registry._sessions.clear()
    registry._loop = None
    obstacle_detector.detection_runner.reset()


def _await_event(ws, wire_type: str, timeout_s: float = RECEIVE_TIMEOUT_S) -> dict | None:
    """Read frames on a daemon thread until `wire_type` shows up.

    TestClient's websocket has no receive timeout, so a missing event would
    hang the whole suite rather than fail it. Other events (mode_change,
    phone_frame, vision_health) share this socket and arrive first.
    """
    out: queue.Queue = queue.Queue()

    def _read():
        try:
            while True:
                msg = json.loads(ws.receive_text())
                if msg.get("type") == wire_type:
                    out.put(msg)
                    return
        except Exception as exc:
            out.put(exc)

    threading.Thread(target=_read, daemon=True).start()
    try:
        result = out.get(timeout=timeout_s)
    except queue.Empty:
        return None
    return None if isinstance(result, Exception) else result


def test_a_sign_photographed_by_the_phone_reaches_the_hud_as_text(app_client):
    client, spoken = app_client

    with client.websocket_connect("/ws/ui") as hud:
        with client.websocket_connect("/ws/phone_stream") as phone:
            phone.send_text(json.dumps({"type": "mode_change", "mode": "read"}))
            phone.send_bytes(_sign_jpeg("PLATFORM 4"))
            event = _await_event(hud, "ocr_read")

    assert event is not None, (
        "the phone sent a legible sign in read mode and no ocr_read ever "
        "reached /ws/ui — the chain is broken somewhere between the frame "
        "socket and the HUD socket"
    )
    text = event["payload"]["text"]
    assert "PLATFORM" in text.upper(), f"HUD received {text!r}"
    # The regression that started this: the digit must survive the whole chain,
    # not just ocr_frame() in isolation.
    assert "4" in text, f"the number was lost end-to-end: {text!r}"
    assert 0.0 < event["payload"]["confidence"] <= 1.0


def test_the_recognized_text_is_also_spoken(app_client):
    """Read mode's primary output is audio — the HUD readout is secondary.
    A chain that publishes the event but never speaks is still broken for the
    user it exists for."""
    client, spoken = app_client

    with client.websocket_connect("/ws/ui") as hud:
        with client.websocket_connect("/ws/phone_stream") as phone:
            phone.send_text(json.dumps({"type": "mode_change", "mode": "read"}))
            phone.send_bytes(_sign_jpeg("EXIT RIGHT"))
            assert _await_event(hud, "ocr_read") is not None

    assert spoken, "nothing was spoken for a legible sign"
    assert "EXIT" in " ".join(spoken).upper(), f"spoken: {spoken!r}"


def test_navigate_mode_does_not_run_ocr(app_client):
    """Guards the mode switch itself: read is the only mode that OCRs, and a
    mode that silently ran the wrong pipeline would still look alive."""
    client, spoken = app_client

    with client.websocket_connect("/ws/ui") as hud:
        with client.websocket_connect("/ws/phone_stream") as phone:
            phone.send_text(json.dumps({"type": "mode_change", "mode": "navigate"}))
            phone.send_bytes(_sign_jpeg("PLATFORM 4"))
            # Short wait: absence is the expected outcome here, so the full
            # timeout would just be dead time in every future suite run.
            assert _await_event(hud, "ocr_read", timeout_s=3.0) is None, (
                "navigate mode produced an ocr_read event"
            )
