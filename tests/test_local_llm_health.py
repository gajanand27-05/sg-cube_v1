"""A dead local Ollama must never sound like mishearing — and must not nag.

The verifier is fail-closed, so an unreachable Ollama rejects every
deep-checked tool. From the outside that is indistinguishable from a bad
transcription, which is how one dead service turns into an afternoon of
debugging the microphone.
"""
import json
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import local_llm_health as h


def _ledger(path) -> list[dict]:
    """The ledger is a plain JSONL file — reading it needs no API."""
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Installed unless a test says otherwise — these tests used to pass only
    # because this dev machine happens to have Ollama.
    monkeypatch.setattr(h, "_binary", lambda: "C:/fake/ollama.exe")
    h._offline, h._pending, h._offline_announced = False, None, False
    yield
    h._offline, h._pending, h._offline_announced = False, None, False


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


def test_restart_is_recorded_with_a_timestamp(tmp_path, monkeypatch):
    """A console log dies with the process. The question is not 'did it
    restart' but 'does something keep killing it', which needs a ledger."""
    monkeypatch.setattr(h, "_RESTART_LOG", tmp_path / "restarts.jsonl")
    calls = {"n": 0}

    def _probe(timeout=2.0):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(h, "is_reachable", _probe)
    monkeypatch.setattr(h, "try_start", lambda: True)

    assert h.ensure_running(wait_s=5) is True
    rows = _ledger(h._RESTART_LOG)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "restarted"
    assert rows[0]["came_up_after_s"] is not None
    # Must be a real, parseable, timezone-aware stamp — "recently" is useless
    # for spotting a pattern across days.
    from datetime import datetime
    assert datetime.fromisoformat(rows[0]["at"]).tzinfo is not None


def test_repeated_restarts_accumulate(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "_RESTART_LOG", tmp_path / "restarts.jsonl")
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    monkeypatch.setattr(h, "try_start", lambda: False)

    for _ in range(3):
        h._offline, h._pending = False, None
        h.ensure_running(wait_s=0.1)

    rows = _ledger(h._RESTART_LOG)
    assert len(rows) == 3, "each attempt must leave its own line"
    assert all(r["outcome"] == "spawn_failed" for r in rows)


def test_no_ledger_file_until_something_restarts(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "_RESTART_LOG", tmp_path / "nope.jsonl")
    assert not (tmp_path / "nope.jsonl").exists()


# ── not installed vs installed-but-down (2026-09-26) ────────────────────

def test_not_installed_is_never_announced(monkeypatch):
    """The laptop floor: no Ollama at all is the normal state, not news."""
    monkeypatch.setattr(h, "_binary", lambda: None)
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    assert h.ensure_running(wait_s=1) is False           # boot path
    assert h.note_failure_if_local_is_down() is True     # mid-turn path
    assert h.take_announcement() is None
    assert h.state() == {"installed": False, "running": False, "state": "not_installed"}


def test_installed_but_down_is_announced_once_per_boot(monkeypatch):
    down = {"v": True}
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: not down["v"])
    monkeypatch.setattr(h, "try_start", lambda: False)
    assert h.ensure_running(wait_s=1) is False
    assert h.take_announcement() == h.OFFLINE_LINE
    assert h.state()["state"] == "offline"

    down["v"] = False                                    # it comes back...
    h.note_reachable()
    assert h.take_announcement() == h.RECOVERED_LINE
    down["v"] = True                                     # ...and drops again
    h.note_failure_if_local_is_down()
    assert h.take_announcement() is None, "offline is spoken once per boot, not per outage"


def test_the_offline_line_says_what_is_true_now():
    """Actions no longer stop without the verifier: they follow the allowlist."""
    assert "can't verify" not in h.OFFLINE_LINE
    assert "confirm" in h.OFFLINE_LINE


def test_preload_speaks_nothing_when_ollama_is_not_installed(monkeypatch):
    from backend.ai_modules.speech import tts_piper
    from backend.daemon import preload
    spoken = []
    monkeypatch.setattr(tts_piper, "speak", spoken.append)
    monkeypatch.setattr(h, "_binary", lambda: None)
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    monkeypatch.setattr("backend.core.memory.embedding.get_embedder",
                        lambda name: (lambda texts: [[0.1] * 384]))
    monkeypatch.setattr("backend.ai_modules.speech.stt_whisper.transcribe_array_cpu",
                        lambda *a, **k: {"text": ""})
    preload._warm()
    assert spoken == []


def test_preload_speaks_once_when_installed_but_down(monkeypatch):
    from backend.ai_modules.speech import tts_piper
    from backend.daemon import preload
    spoken = []
    monkeypatch.setattr(tts_piper, "speak", spoken.append)
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    monkeypatch.setattr(h, "try_start", lambda: False)
    monkeypatch.setattr("backend.core.memory.embedding.get_embedder",
                        lambda name: (lambda texts: [[0.1] * 384]))
    monkeypatch.setattr("backend.ai_modules.speech.stt_whisper.transcribe_array_cpu",
                        lambda *a, **k: {"text": ""})
    preload._warm()
    preload._warm()
    assert spoken == [h.OFFLINE_LINE]


def test_diagnostics_reports_the_live_state(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.server.main import app
    monkeypatch.setattr(h, "_binary", lambda: None)
    monkeypatch.setattr(h, "is_reachable", lambda timeout=2.0: False)
    body = TestClient(app, client=("127.0.0.1", 50000)).get("/diagnostics/hardware").json()
    assert body["local_models"] == {"installed": False, "running": False, "state": "not_installed"}
    assert "boot" in body
