"""Phone stream Phase 1: frame ingestion, throttle, latest-frame HTTP fetch.

Routes are mounted on a minimal FastAPI app — the full server lifespan (LLM
boot, services) is not under test here. The browser seam is covered by the
manual Playwright probe, not these tests.
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.vision import frame_ingest
from backend.core.vision.frame_ingest import FrameIngestor
from backend.server.routes import phone_stream

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100  # fake but recognizable payload


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(phone_stream.router)
    app.include_router(phone_stream.page_router)
    # fresh global ingestor per test — module-level singleton
    fresh = FrameIngestor(max_fps=2.0)
    orig = frame_ingest.frame_ingestor
    frame_ingest.frame_ingestor = fresh
    phone_stream.frame_ingestor = fresh
    yield TestClient(app)
    frame_ingest.frame_ingestor = orig
    phone_stream.frame_ingestor = orig


def test_no_frame_yet_404(client):
    assert client.get("/vision/phone_frame").status_code == 404


def test_binary_frame_reaches_http_fetch(client):
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_bytes(JPEG)
        # receive loop is async on the same connection; closing flushes it
    r = client.get("/vision/phone_frame")
    assert r.status_code == 200
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-frame-id"] == "1"
    assert r.headers["cache-control"] == "no-store"


def test_mode_change_tags_subsequent_frames(client):
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_text('{"type": "mode_change", "mode": "navigate"}')
        ws.send_bytes(JPEG)
    r = client.get("/vision/phone_frame")
    assert r.status_code == 200
    assert r.headers["x-frame-mode"] == "navigate"


def test_invalid_json_does_not_kill_stream(client):
    with client.websocket_connect("/ws/phone_stream") as ws:
        ws.send_text("{not json")
        ws.send_bytes(JPEG)
    assert client.get("/vision/phone_frame").status_code == 200


def test_phone_connect_returns_concrete_url(client):
    r = client.get("/vision/phone_connect")
    assert r.status_code == 200
    data = r.json()
    # A real dotted-quad URL, never a placeholder like <pc-ip>
    assert data["url"] is None or (
        data["url"].startswith("http://")
        and data["url"].endswith(":8001/phone" if ":8001" in data["url"] else "/phone")
        and "<" not in data["url"]
    )


def test_phone_connect_qr_is_png(client):
    if client.get("/vision/phone_connect").json()["url"] is None:
        pytest.skip("no LAN interface on this machine")
    r = client.get("/vision/phone_connect_qr.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_phone_page_served(client):
    r = client.get("/phone")
    assert r.status_code == 200
    assert "getUserMedia" in r.text
    assert "/ws/phone_stream" in r.text


def test_throttle_drops_fast_frames(monkeypatch):
    ing = FrameIngestor(max_fps=2.0)
    t = [1000.0]
    monkeypatch.setattr(frame_ingest.time, "monotonic", lambda: t[0])
    assert ing.ingest_frame(b"frame-a") is not None
    t[0] += 0.1  # 100ms later — under the 500ms floor
    assert ing.ingest_frame(b"frame-b") is None
    latest, meta = ing.latest_frame()
    assert latest == b"frame-a" and meta.frame_id == 1
    t[0] += 0.5
    assert ing.ingest_frame(b"frame-c").frame_id == 2
    assert ing.stats["frames_dropped"] == 1


def test_oversized_and_empty_frames_rejected():
    ing = FrameIngestor(max_fps=100.0)
    assert ing.ingest_frame(b"") is None
    assert ing.ingest_frame(b"x" * (frame_ingest.MAX_FRAME_BYTES + 1)) is None
    assert ing.latest_frame() == (None, None)


def test_private_peer_guard():
    assert phone_stream._peer_allowed("127.0.0.1")
    assert phone_stream._peer_allowed("192.168.1.50")
    assert phone_stream._peer_allowed("testclient")
    assert phone_stream._peer_allowed(None)
    assert not phone_stream._peer_allowed("8.8.8.8")
    assert not phone_stream._peer_allowed("1.1.1.1")
