"""Watcher actions are fixed tool calls, gated at setup and again at fire time.

A watcher used to store free text and hand it to the planner when it fired,
under trigger source None — which the verifier reads as an explicit wake — so
trusted tools ran with no check and destructive ones asked an empty room
"should I proceed?".
"""
import asyncio

import pytest

import backend.core.tools  # noqa: F401  (registers every tool)
from backend.core.agent import tool_policy, verifier
from backend.core.agents.watcher import watcher
from backend.core.state import manager as state_manager
from backend.core.tools import registry as tool_registry
from backend.daemon import trigger
from backend.daemon.ui_events import ProactiveEvent


@pytest.fixture(autouse=True)
def _clean_watcher(monkeypatch):
    monkeypatch.setattr(watcher, "tasks", [])
    yield
    state_manager._voice_trigger_source = None


def _battery(**kw):
    return tool_registry.REGISTRY["monitor_battery"].func(threshold_pct=20, **kw)


@pytest.mark.parametrize("tool,args,why", [
    ("delete_file", {"file": "notes.txt"}, "destructive"),
    ("run_command", {"command": "dir"}, "destructive"),
    ("write_file", {"path": "a.txt", "content": "x"}, "allowlist"),       # HUD tool: nobody to say yes
    ("monitor_folder", {"folder_path": "~", "file_pattern": "*"}, "another background action"),
    ("definitely_not_a_tool", {}, "not a known tool"),
    ("set_volume", {}, "Missing required argument"),
])
def test_setup_refuses_what_cannot_run_unattended(tool, args, why):
    res = _battery(action_tool=tool, action_args=args)
    assert res.status != "success", res
    assert why in (res.reason or res.message or "")
    assert watcher.tasks == [], "a refused action must not be registered"


def test_setup_echoes_the_exact_call_it_will_run():
    res = _battery(announce="Battery is low", action_tool="set_brightness",
                   action_args={"level": 30})
    assert res.status == "success"
    assert 'run set_brightness({"level": 30})' in res.message
    assert "say 'Battery is low'" in res.message
    assert watcher.tasks[0]["action"] == {
        "announce": "Battery is low", "tool": "set_brightness", "args": {"level": 30}}


def test_setup_needs_something_to_do():
    assert _battery().status != "success"


def _fire(event, monkeypatch):
    calls, spoken, sources = [], [], []

    async def fake_call(name, args):
        calls.append((name, args))
        sources.append(state_manager._voice_trigger_source)
        return tool_registry.ToolResult.success(f"{name} done")

    async def fake_speak(text, device_id=None):
        spoken.append(text)

    monkeypatch.setattr(tool_registry, "call", fake_call)
    monkeypatch.setattr(trigger, "_speak_selective", fake_speak)
    asyncio.run(trigger._handle_proactive_async(event))
    return calls, spoken, sources


def test_fire_runs_the_fixed_call_under_the_background_source(monkeypatch):
    calls, spoken, sources = _fire(
        ProactiveEvent(query="Battery is at 18%.", tool="set_brightness", args={"level": 30}),
        monkeypatch)
    assert calls == [("set_brightness", {"level": 30})]
    assert sources == ["background"]
    assert spoken == ["Battery is at 18%. set_brightness done"]
    assert state_manager._voice_trigger_source is None, "source must not leak into the next turn"


def test_fire_rechecks_and_refuses_a_destructive_call(monkeypatch):
    """Setup refuses these, but the event is data on a bus — check again."""
    calls, spoken, _ = _fire(ProactiveEvent(query="", tool="delete_file",
                                            args={"file": "x"}), monkeypatch)
    assert calls == []
    assert "did not run" in spoken[0] and "destructive" in spoken[0]


def test_announce_only_runs_no_tool(monkeypatch):
    calls, spoken, _ = _fire(ProactiveEvent(query="A new PDF arrived."), monkeypatch)
    assert calls == [] and spoken == ["A new PDF arrived."]


def _verify(name, args):
    return asyncio.run(verifier.verify("", {"name": name, "args": args, "confidence": 1.0}))


def test_verifier_background_source_enforces_the_allowlist(monkeypatch):
    async def no_deep_check(*a, **k):
        pytest.fail("the allowlist is the check in the background; phi3 must not be consulted")

    monkeypatch.setattr(verifier, "_secondary_check", no_deep_check)
    state_manager._voice_trigger_source = "background"
    assert not _verify("delete_file", {"file": "x"}).is_valid
    assert not _verify("write_file", {"path": "a", "content": "b"}).is_valid
    assert _verify("get_battery", {}).is_valid
    ok = _verify("set_volume", {"level": 20})
    assert ok.is_valid and not ok.needs_confirmation


def test_every_listed_tool_exists():
    """A typo in the allowlist silently refuses a tool forever."""
    listed = tool_policy.ALLOW | tool_policy.HUD_CONFIRM
    assert listed <= set(tool_registry.REGISTRY), listed - set(tool_registry.REGISTRY)
