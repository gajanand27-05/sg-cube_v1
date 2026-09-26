"""With no HUD connected, confirmation falls back to voice alone — with the
same guarantees, and never an auto-allow. Measured before writing any code:
nothing in the confirmation path depends on a HUD client (the pending lives
in pending_confirmation.store, which voice answers too), so these pin that.
Driven through the real Commander; only the planner and phi3 are stubbed."""
import asyncio
import time

import pytest

import backend.core.tools  # noqa: F401
from backend.core.agent import verifier
from backend.core.agent.context import ConversationContext
from backend.core.agents import commander as cmd
from backend.core.agents import pending_confirmation as pcm
from backend.server.ws_ui import get_manager


class _Planner:
    def __init__(self, script):
        self.script = list(script)

    async def generate_plan_stream(self, text, history, agent_context):
        yield {"type": "final", "content": self.script.pop(0)}


def _turn(text, script=()):
    cmd.commander.planner = _Planner(script)
    ctx = ConversationContext(session_id="no-hud")
    out = []

    async def go():
        async for c in cmd.commander.run_stream(text, ctx, "u"):
            out.append(c)
    asyncio.run(go())
    return " ".join(str(c.content) for c in out if getattr(c, "type", "") == "final_response")


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    from backend.core.tools import files
    monkeypatch.setattr(files, "SEARCH_ROOTS", [tmp_path])

    async def phi3_ok(*a, **k):
        return True
    monkeypatch.setattr(verifier, "_secondary_check", phi3_ok)
    assert get_manager()._connections == [], "precondition: no HUD connected"
    pcm.store.clear_all()
    real_planner = cmd.commander.planner   # a module singleton: put it back
    yield
    cmd.commander.planner = real_planner
    pcm.store.clear_all()


def _ask(tmp_path):
    target = tmp_path / "note.txt"
    spoken = _turn("write hi into note.txt",
                   [{"tool_calls": [{"name": "write_file",
                                     "args": {"path": str(target), "content": "hi"}}]}])
    assert "permission" in spoken.lower() and str(target) in spoken, spoken
    assert not target.exists(), "never auto-allowed, HUD or not"
    return target


def test_voice_yes_runs_it(tmp_path):
    target = _ask(tmp_path)
    _turn("yes")
    assert target.read_text() == "hi"


def test_voice_no_refuses(tmp_path):
    target = _ask(tmp_path)
    _turn("no")
    assert not target.exists()


def test_a_second_yes_does_not_run_it_again(tmp_path):
    target = _ask(tmp_path)
    _turn("yes")
    target.unlink()
    _turn("yes", [{"final_response": "Yes to what?"}])
    assert not target.exists(), "single use: the pending was consumed by the first yes"


def test_timeout_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(pcm.settings, "confirmation_ttl_s", 0.2)
    target = _ask(tmp_path)
    time.sleep(0.5)
    _turn("yes", [{"final_response": "Yes to what?"}])
    assert not target.exists()
