"""When local Ollama is down there is no phi3 deep check. Instead of rejecting
every deep-checked tool (which sounded exactly like being misheard), the
verifier falls back to the reviewed allowlist in tool_policy:
ALLOW runs, HUD_CONFIRM asks, everything else is refused."""
import asyncio

import pytest

import backend.core.tools  # noqa: F401
from backend.core.agent import verifier
from backend.core.state import manager as state_manager


@pytest.fixture
def ollama_down(monkeypatch):
    async def unavailable(*a, **k):
        return None
    monkeypatch.setattr(verifier, "_secondary_check", unavailable)


@pytest.fixture(autouse=True)
def _reset_source():
    yield
    state_manager._voice_trigger_source = None


def _verify(name, args, source=None):
    state_manager._voice_trigger_source = source
    return asyncio.run(verifier.verify("", {"name": name, "args": args, "confidence": 1.0}))


def test_allowlisted_tool_runs_on_a_follow_up_turn(ollama_down):
    """Trusted system-write on a follow-up is exactly the case that reached
    phi3 and got rejected when Ollama was off."""
    r = _verify("set_volume", {"level": 30}, source="followup")
    assert r.is_valid and not r.needs_confirmation


def test_untrusted_allowlisted_tool_runs(ollama_down):
    r = _verify("add_contact", {"name": "Asha", "phone": "+919876543210"})
    assert r.is_valid and not r.needs_confirmation


def test_hud_tool_asks(ollama_down):
    r = _verify("write_file", {"path": "a.txt", "content": "x"})
    assert r.is_valid and r.needs_confirmation and not r.is_critical


def test_destructive_hud_tool_asks_as_critical(ollama_down):
    r = _verify("shutdown_pc", {"seconds": 10})
    assert r.is_valid and r.needs_confirmation and r.is_critical


def test_unlisted_tool_is_refused(ollama_down):
    r = _verify("run_command", {"command": "whoami"})
    assert not r.is_valid and "Ollama is not running" in r.error


@pytest.mark.parametrize("name,args", [
    ("remember", {"fact": "my cat is Luna"}),
    ("set_preference", {"preference": "dark mode"}),
])
def test_memory_writes_ask_only_on_low_confidence_turns(ollama_down, name, args):
    assert _verify(name, args, source="followup").needs_confirmation
    assert _verify(name, args, source="barge_in").needs_confirmation
    wake = _verify(name, args, source="wake")
    assert wake.is_valid and not wake.needs_confirmation


def test_a_guard_objection_still_asks(ollama_down, monkeypatch):
    from backend.core.tools.registry import REGISTRY
    monkeypatch.setattr(REGISTRY["close_app"], "confirm_if", lambda a: "unsaved work")
    r = _verify("close_app", {"name": "code"})
    assert r.is_valid and r.needs_confirmation


def test_a_real_rejection_is_still_a_rejection(monkeypatch):
    """Ollama up and phi3 says no (or answers garbage): fail closed as before."""
    async def rejected(*a, **k):
        return False
    monkeypatch.setattr(verifier, "_secondary_check", rejected)
    assert not _verify("write_file", {"path": "a.txt", "content": "x"}).is_valid


def test_secondary_check_reports_unavailable_only_when_ollama_is_down(monkeypatch):
    from backend.core import local_llm_health

    class _Boom:
        async def generate(self, *a, **k):
            raise ConnectionError("refused")

    monkeypatch.setattr(verifier, "get_provider", lambda: _Boom())
    monkeypatch.setattr(local_llm_health, "note_failure_if_local_is_down", lambda: True)
    assert asyncio.run(verifier._secondary_check("q", "t", {}, "")) is None
    monkeypatch.setattr(local_llm_health, "note_failure_if_local_is_down", lambda: False)
    assert asyncio.run(verifier._secondary_check("q", "t", {}, "")) is False
