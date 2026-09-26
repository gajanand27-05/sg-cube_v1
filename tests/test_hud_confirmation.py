"""HUD confirmations: single-use, short-lived, bound to the exact tool and
arguments; the WebSocket that carries them checks Origin and a session token;
voice answers the same pending; a timeout is a refusal."""
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

import backend.core.tools  # noqa: F401
from backend.core.agents import pending_confirmation as pcm
from backend.core.agents.pending_confirmation import Pending, store
from backend.daemon.main import RedactingFormatter
from backend.server import hud_confirm, session

LOOPBACK = ("127.0.0.1", 50123)


@pytest.fixture(autouse=True)
def _tmp_is_a_user_folder(tmp_path, monkeypatch):
    """These tests are about execution, not path policy: let the file tools
    write into this test's temp dir (files.check_user_path)."""
    from backend.core.tools import files as _files
    monkeypatch.setattr(_files, "SEARCH_ROOTS", [tmp_path])


@pytest.fixture
def app():
    from backend.server.main import app
    return app


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    spoken = []

    async def record(text):
        spoken.append(text)

    monkeypatch.setattr(hud_confirm, "_speak", record)
    store.clear_all()
    yield spoken
    store.clear_all()


# ── origin / host / token rules ─────────────────────────────────────────

@pytest.mark.parametrize("origin,host,ok", [
    (None, "127.0.0.1:8001", True),                          # non-browser client
    ("http://127.0.0.1:8001", "127.0.0.1:8001", True),       # the served HUD
    ("http://localhost:8001", "127.0.0.1:8001", True),
    ("http://localhost:5173", "127.0.0.1:8001", True),       # vite dev server
    ("https://evil.example", "127.0.0.1:8001", False),       # any website
    ("http://127.0.0.1:9999", "127.0.0.1:8001", False),      # another local app
    ("http://192.168.1.20:8001", "192.168.1.20:8001", False),  # LAN, not allowed
    ("null", "127.0.0.1:8001", False),                       # sandboxed iframe / file://
])
def test_origin_rules(origin, host, ok):
    assert session.origin_ok(origin, host, allow_lan=False) is ok


def test_lan_origin_only_when_opted_in():
    assert session.origin_ok("http://192.168.1.20:8001", "192.168.1.20:8001", allow_lan=True)


def test_rebound_hostname_is_refused():
    assert not session.host_header_ok("evil.example:8001", allow_lan=True)
    assert session.host_header_ok("127.0.0.1:8001", allow_lan=False)


def test_token_is_compared_exactly():
    assert session.token_ok(session.TOKEN)
    assert not session.token_ok(None) and not session.token_ok(session.TOKEN[:-1])


def test_session_endpoint(app):
    c = TestClient(app, client=LOOPBACK)
    assert c.get("/api/session", headers={"host": "127.0.0.1:8001"}).json()["token"] == session.TOKEN
    assert c.get("/api/session", headers={"host": "evil.example:8001"}).status_code == 403
    assert c.get("/api/session", headers={"host": "127.0.0.1:8001",
                                          "origin": "https://evil.example"}).status_code == 403


def _reject_code(app, url, headers=None):
    """Close code a client sees — at the handshake (bad Origin) or, for a bad
    token, right after it: the server accepts then closes 4401 so a real
    browser receives the code instead of a bare 1006."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with TestClient(app, client=LOOPBACK).websocket_connect(url, headers=headers or {}) as ws:
            ws.receive_text()
    return e.value.code


def test_ws_requires_the_token(app):
    assert _reject_code(app, "/ws/ui") == 4401
    assert _reject_code(app, "/ws/ui?token=stale") == 4401


def test_ws_refuses_a_foreign_origin_even_with_the_token(app):
    code = _reject_code(app, f"/ws/ui?token={session.TOKEN}",
                        headers={"origin": "https://evil.example"})
    assert code == 4403


# ── answering over the socket ───────────────────────────────────────────

def _pending(tmp_path, name="write_file"):
    target = tmp_path / "confirmed.txt"
    p = Pending(calls=[{"name": name, "args": {"path": str(target), "content": "ok"}}],
                user_query="write it", tool_name="write file", prompt="Write it?")
    store.remember("s1", p)
    return p, target


def _answer(ws, p, decision="yes", digest=None):
    ws.send_text(json.dumps({"type": "confirm_response", "id": p.id,
                             "digest": digest or p.digest, "decision": decision}))
    while True:
        msg = json.loads(ws.receive_text())
        if msg["type"] == "confirmation_ack":
            return msg["payload"]


def _ws(app):
    return TestClient(app, client=LOOPBACK).websocket_connect(
        f"/ws/ui?token={session.TOKEN}", headers={"origin": "http://127.0.0.1:8001",
                                                  "host": "127.0.0.1:8001"})


def test_yes_runs_exactly_the_approved_call_once(app, tmp_path, _clean):
    p, target = _pending(tmp_path)
    with _ws(app) as ws:
        first = _answer(ws, p)
        second = _answer(ws, p)
    assert first["ok"] and target.read_text() == "ok"
    assert not second["ok"] and "already answered" in second["message"]
    assert _clean == ["wrote 2 bytes to confirmed.txt"], "spoken outcome, confirmed by the read-back post-condition"


def test_no_runs_nothing(app, tmp_path):
    p, target = _pending(tmp_path)
    with _ws(app) as ws:
        assert _answer(ws, p, "no")["ok"]
    assert not target.exists()


def test_an_answer_for_different_arguments_is_refused_and_not_consumed(app, tmp_path):
    p, target = _pending(tmp_path)
    other = pcm.calls_digest([{"name": "write_file", "args": {"path": "C:/other", "content": "x"}}])
    with _ws(app) as ws:
        bad = _answer(ws, p, digest=other)
        assert not bad["ok"] and "does not match" in bad["message"]
        assert not target.exists()
        assert _answer(ws, p)["ok"], "a mismatched answer must not consume the real one"
    assert target.exists()


def test_voice_and_hud_share_one_slot(app, tmp_path):
    p, target = _pending(tmp_path)
    assert store.take("s1") is p            # voice got there first
    with _ws(app) as ws:
        assert not _answer(ws, p)["ok"]
    assert not target.exists()


def test_timeout_is_a_refusal_and_the_hud_is_told(monkeypatch, tmp_path):
    published = []
    monkeypatch.setattr(pcm, "_publish", published.append)
    monkeypatch.setattr(pcm.settings, "confirmation_ttl_s", 0.2)
    p, target = _pending(tmp_path)
    time.sleep(1.0)
    assert [(type(e).__name__, getattr(e, "outcome", None)) for e in published] == [
        ("ConfirmationRequested", None), ("ConfirmationResolved", "expired")]
    got, why = store.take_by_id(p.id, p.digest)
    assert got is None and not target.exists()


def test_the_request_event_carries_what_the_dialog_needs(monkeypatch, tmp_path):
    published = []
    monkeypatch.setattr(pcm, "_publish", published.append)
    p, _ = _pending(tmp_path)
    req = published[0]
    assert (req.id, req.digest, req.prompt) == (p.id, p.digest, "Write it?")
    assert req.expires_in_s == pcm.settings.confirmation_ttl_s


def test_the_session_token_never_reaches_the_log():
    rec = logging.LogRecord("uvicorn.error", 20, "", 0,
                            '127.0.0.1:1 - "WebSocket /ws/ui?token=abc_DEF-123" 403', None, None)
    out = RedactingFormatter("%(message)s").format(rec)
    assert "abc_DEF-123" not in out and "token=<redacted>" in out


# ── the voice/HUD race ──────────────────────────────────────────────────

def test_racing_answers_consume_exactly_once(tmp_path):
    """Voice and HUD answer from different threads; the store's lock must let
    exactly one of them win, however they interleave."""
    import threading
    p, _ = _pending(tmp_path)
    wins, go = [], threading.Barrier(16)

    def voice():
        go.wait()
        if store.take("s1") is not None:
            wins.append("voice")

    def hud():
        go.wait()
        got, _ = store.take_by_id(p.id, p.digest)
        if got is not None:
            wins.append("hud")

    ts = [threading.Thread(target=voice if i % 2 else hud) for i in range(16)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1, wins


def test_a_late_hud_answer_is_ignored_and_says_who_won(app, tmp_path, caplog):
    p, target = _pending(tmp_path)
    assert store.take("s1") is p                       # voice won
    with caplog.at_level("INFO"), _ws(app) as ws:
        ack = _answer(ws, p)
    assert not ack["ok"] and ack["message"] == "already answered by voice"
    assert "HUD answer ignored" in caplog.text
    assert not target.exists()
