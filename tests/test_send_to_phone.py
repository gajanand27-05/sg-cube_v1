"""send_to_phone used to report "Sent ... to mobile device" whether or not any
phone was connected. It must refuse when nothing would receive the handover,
and claim dispatch (not delivery) when something would."""
import types

import pytest

import backend.core.tools  # noqa: F401
from backend.core.tools.registry import REGISTRY
from backend.server.routes import remote

send = REGISTRY["send_to_phone"].func


@pytest.fixture
def published(monkeypatch):
    seen = []
    monkeypatch.setattr("backend.core.tools.comms.get_bus",
                        lambda: types.SimpleNamespace(publish=seen.append))
    return seen


def test_no_phone_connected_is_an_error_and_sends_nothing(monkeypatch, published):
    monkeypatch.setattr(remote.manager, "active_connections", {})
    res = send("https://example.com", is_url=True)
    assert res.status == "error"
    assert "No phone is connected" in res.reason
    assert published == []


def test_connected_but_no_loop_counts_as_unreachable(monkeypatch, published):
    """_broadcast_event silently skips without a captured loop."""
    conn = types.SimpleNamespace(is_active=True)
    monkeypatch.setattr(remote.manager, "active_connections", {"p1": conn})
    monkeypatch.setattr(remote.manager, "loop", None)
    assert send("hi").status == "error"
    assert published == []


def test_live_phone_gets_it_and_the_claim_is_dispatch(monkeypatch, published):
    monkeypatch.setattr(remote.manager, "loop", types.SimpleNamespace(is_running=lambda: True))
    monkeypatch.setattr(remote.manager, "active_connections", {
        "p1": types.SimpleNamespace(is_active=True),
        "dead": types.SimpleNamespace(is_active=False),
    })
    res = send("hello there")
    assert res.status == "success"
    assert "1 connected device" in res.message and "not confirmed" in res.message
    assert len(published) == 1 and published[0].text == "hello there"
