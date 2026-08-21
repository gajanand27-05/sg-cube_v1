"""Desktop-sensitive routes must not be reachable from the LAN.

Any deployment that binds APP_HOST=0.0.0.0 exposes /vision/screenshot (a live
JPEG of the user's desktop), /memory/*, /system/*, /agents, /diagnostics/* and
WS /ws/ui, unauthenticated, to anything on the same Wi-Fi. The phone-camera
feature was the original reason to bind wide; it is gone, but the guard is not
contingent on it — ALLOW_LAN_HUD still opens the same door on request.

The HUD sends no credential, so the guard is peer-based, not token-based:
loopback only, widened to RFC1918 by ALLOW_LAN_HUD for the user who opens the
HUD via the machine's LAN IP. These asserts are the tripwire for both halves —
a regression that drops the guard, and one that widens it by default.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import deps
from backend.core.auth.deps import peer_allowed, require_local_peer
from backend.server.routes import agents, diagnostics, memory, remote, system, ui, vision

LAN = ("192.168.1.50", 4000)
LOOPBACK = ("127.0.0.1", 4000)


@pytest.fixture()
def app():
    app = FastAPI()
    app.include_router(system.router)
    app.include_router(ui.router)
    return app


# ── the predicate ────────────────────────────────────────────────────

def test_loopback_allowed_lan_refused_by_default():
    assert peer_allowed("127.0.0.1")
    assert peer_allowed("::1")
    assert not peer_allowed("192.168.1.50")
    assert not peer_allowed("10.0.0.7")
    assert not peer_allowed("172.16.4.4")
    assert not peer_allowed("8.8.8.8")
    assert not peer_allowed("not-an-ip")


def test_allow_lan_hud_widens_to_private_only(monkeypatch):
    monkeypatch.setattr(deps.settings, "allow_lan_hud", True)
    assert peer_allowed("192.168.1.50")
    assert peer_allowed("10.0.0.7")
    assert peer_allowed("127.0.0.1")
    # ...but never the public internet, even with the escape hatch on.
    assert not peer_allowed("8.8.8.8")
    assert not peer_allowed("172.32.0.1")  # outside 172.16.0.0/12


# ── HTTP ─────────────────────────────────────────────────────────────

def test_lan_peer_gets_clean_403(app):
    r = TestClient(app, client=LAN).get("/system/stats")
    assert r.status_code == 403
    assert "local machine" in r.json()["detail"]


def test_loopback_peer_allowed(app):
    assert TestClient(app, client=LOOPBACK).get("/system/stats").status_code == 200


def test_lan_peer_allowed_when_opted_in(app, monkeypatch):
    monkeypatch.setattr(deps.settings, "allow_lan_hud", True)
    assert TestClient(app, client=LAN).get("/system/stats").status_code == 200


@pytest.mark.parametrize("module", [vision, memory, system, agents, diagnostics])
def test_every_sensitive_router_carries_the_guard(module):
    """Router-level dependency, so a route added later inherits it."""
    calls = [d.dependency for d in module.router.dependencies]
    assert require_local_peer in calls, f"{module.__name__} is unguarded"


# ── WebSocket ────────────────────────────────────────────────────────

def test_ws_ui_closes_lan_peer(app):
    with pytest.raises(Exception):
        # Starlette raises WebSocketDisconnect on a rejected handshake.
        with TestClient(app, client=LAN).websocket_connect("/ws/ui"):
            pass


def test_ws_ui_accepts_loopback(app):
    with TestClient(app, client=LOOPBACK).websocket_connect("/ws/ui") as ws:
        assert ws is not None


# ── remote.py: the bridge that never ran ─────────────────────────────

def test_remote_connect_sets_up_event_bridge():
    """_setup_event_bridge() used to hang off _get_bus(), which had exactly
    one occurrence in the repo: its own definition. So subscribe() never ran
    and a connected Android client got zero events, forever."""
    from backend.core.events import get_bus
    from backend.core.state import StateChangedEvent

    remote.manager._bridged_bus = None
    app = FastAPI()
    app.include_router(remote.router)
    with TestClient(app, client=LOOPBACK).websocket_connect("/remote/connect/dev1") as ws:
        assert ws.receive_json()["type"] == "ConfigSync"

    # The bus INSTANCE, not a bool: a bridge latched onto a discarded bus
    # satisfies a flag check while dropping every event.
    assert remote.manager._bridged_bus is get_bus()
    subs = get_bus()._subscribers[StateChangedEvent]
    assert remote.manager._broadcast_event in subs


def test_remote_audio_buffer_is_capped():
    """No cap meant a client streaming binary without end_of_speech grew a
    server-side bytearray until OOM."""
    assert remote.MAX_AUDIO_BUFFER_BYTES == 32_000 * 60

    app = FastAPI()
    app.include_router(remote.router)
    chunk = b"\x00" * 320_000  # 10s of 16kHz PCM
    with TestClient(app, client=LOOPBACK).websocket_connect("/remote/connect/dev2") as ws:
        ws.receive_json()
        for _ in range(8):  # 2.56 MB — past the ~1.92 MB cap
            ws.send_bytes(chunk)
        ws.send_text('{"type": "set_codec", "payload": {"codec": "pcm"}}')
        conn = remote.manager.active_connections["dev2"]
        assert len(conn.audio_buffer) <= remote.MAX_AUDIO_BUFFER_BYTES
