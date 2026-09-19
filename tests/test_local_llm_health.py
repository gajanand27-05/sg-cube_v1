"""A dead local Ollama must never sound like mishearing — and must not nag.

The verifier is fail-closed, so an unreachable Ollama rejects every
deep-checked tool. From the outside that is indistinguishable from a bad
transcription, which is how one dead service turns into an afternoon of
debugging the microphone.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import local_llm_health as h


@pytest.fixture(autouse=True)
def _clean():
    h._reset_for_tests()
    yield
    h._reset_for_tests()


def test_offline_is_announced_exactly_once(monkeypatch):
    monkeypatch.setattr(h, "is_reachable", lambda timeout=1.5: False)

    assert h.note_failure_if_local_is_down() is True
    assert h.take_announcement() == h.OFFLINE_LINE

    # A persistent outage must not re-announce on every single turn.
    for _ in range(5):
        h.note_failure_if_local_is_down()
        assert h.take_announcement() is None


def test_recovery_is_announced_once(monkeypatch):
    monkeypatch.setattr(h, "is_reachable", lambda timeout=1.5: False)
    h.note_failure_if_local_is_down()
    h.take_announcement()                     # consume the offline notice

    h.note_reachable()
    assert h.take_announcement() == h.RECOVERED_LINE
    assert h.take_announcement() is None
    h.note_reachable()
    assert h.take_announcement() is None, "steady-state healthy must stay silent"


def test_healthy_start_says_nothing(monkeypatch):
    """No spurious 'back online' every time the daemon boots healthy."""
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: True)
    assert h.ensure_running() is True
    assert h.take_announcement() is None


def test_autostart_success_is_silent(monkeypatch):
    """If we quietly fixed it, there is nothing to tell the user."""
    calls = {"probe": 0}

    def _probe(timeout=2.0):
        calls["probe"] += 1
        return calls["probe"] > 1          # down first, up after the start

    monkeypatch.setattr(h, "is_reachable", _probe)
    monkeypatch.setattr(h, "try_start", lambda: True)

    assert h.ensure_running(wait_s=5) is True
    assert h.take_announcement() is None


def test_failure_to_start_announces(monkeypatch):
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    monkeypatch.setattr(h, "try_start", lambda: False)

    assert h.ensure_running(wait_s=1) is False
    assert h.take_announcement() == h.OFFLINE_LINE


def test_a_reachable_service_is_not_blamed(monkeypatch):
    """If Ollama answers, the failure was something else and must NOT be
    reported as 'local models are offline'."""
    monkeypatch.setattr(h, "is_reachable", lambda timeout=1.5: True)
    assert h.note_failure_if_local_is_down() is False
    assert h.take_announcement() is None


def test_start_is_detached(monkeypatch):
    """Started as an ordinary child, Ollama would die with the daemon — so a
    restart of Jarvis would take the local models down with it."""
    seen = {}

    class _P:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw

    monkeypatch.setattr(h.subprocess, "Popen", _P)
    monkeypatch.setattr(h, "_binary", lambda: "ollama")

    assert h.try_start() is True
    assert seen["cmd"][1] == "serve"
    import os
    if os.name == "nt":
        assert seen["kw"].get("creationflags", 0) & 0x00000008, "DETACHED_PROCESS"
    else:
        assert seen["kw"].get("start_new_session") is True


def test_missing_binary_does_not_raise(monkeypatch):
    monkeypatch.setattr(h, "_binary", lambda: None)
    assert h.try_start() is False
