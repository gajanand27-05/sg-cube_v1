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
    ("delete_file", {"file": "notes.txt"}, "only read-only"),
    ("run_command", {"command": "dir"}, "only read-only"),
    ("write_file", {"path": "a.txt", "content": "x"}, "only read-only"),   # HUD tool: nobody to say yes
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
    res = _battery(announce="Battery is low", action_tool="find_file",
                   action_args={"query": "report"})
    assert res.status == "success"
    assert 'run find_file({"query": "report"})' in res.message
    assert "say 'Battery is low'" in res.message
    assert watcher.tasks[0]["action"] == {
        "announce": "Battery is low", "tool": "find_file", "args": {"query": "report"},
        "fingerprint": tool_policy.policy_fingerprint("find_file")}


def test_setup_needs_something_to_do():
    assert _battery().status != "success"


def _fire(event, monkeypatch):
    calls, spoken, sources = [], [], []

    async def fake_call(name, args, approved=False):
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
        ProactiveEvent(query="Battery is at 18%.", tool="find_file", args={"query": "report"}),
        monkeypatch)
    assert calls == [("find_file", {"query": "report"})]
    assert sources == ["background"]
    assert spoken == ["Battery is at 18%. find_file done"]
    assert state_manager._voice_trigger_source is None, "source must not leak into the next turn"


def test_fire_rechecks_and_refuses_a_destructive_call(monkeypatch):
    """Setup refuses these, but the event is data on a bus — check again."""
    calls, spoken, _ = _fire(ProactiveEvent(query="", tool="delete_file",
                                            args={"file": "x"}), monkeypatch)
    assert calls == []
    assert "did not run" in spoken[0] and "only read-only" in spoken[0]


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
    assert not _verify("set_volume", {"level": 20}).is_valid, "ALLOW is not enough in the background"
    ok = _verify("get_battery", {})
    assert ok.is_valid and not ok.needs_confirmation


@pytest.mark.parametrize("tool,args", [
    ("add_contact", {"name": "Asha", "phone": "+919876543210"}),
    ("send_email", {"to": "a@b.com", "subject": "hi"}),
    ("send_whatsapp", {"contact": "Asha", "message": "hi"}),
    ("monitor_battery", {"threshold_pct": 10, "announce": "x"}),
    ("set_reminder", {"minutes": 5, "message": "x"}),
])
def test_watchers_run_read_only_tools_and_nothing_else(tool, args):
    """Decided 2026-09-26: a fired watcher may announce and run read-only
    tools only. These three were allowed before (ALLOW, not destructive)."""
    res = _battery(announce="x", action_tool=tool, action_args=args)
    reason = res.reason or ""
    assert res.status != "success", res
    assert "only read-only" in reason or "another background action" in reason, reason
    assert watcher.tasks == []
    assert tool_policy.background_refusal(tool, args)


def test_every_listed_tool_exists():
    """A typo in the allowlist silently refuses a tool forever."""
    listed = tool_policy.ALLOW | tool_policy.HUD_CONFIRM
    assert listed <= set(tool_registry.REGISTRY), listed - set(tool_registry.REGISTRY)


# ── a confirmation that no longer covers what would run ─────────────────

def _registered(monkeypatch, **action_kw):
    _battery(announce="low", action_tool="find_file", action_args={"query": "report"})
    task = watcher.tasks[0]
    task["action"].update(action_kw)
    published = []
    monkeypatch.setattr("backend.core.agents.watcher.get_bus",
                        lambda: type("B", (), {"publish": lambda self, e: published.append(e)})())
    return task, published


def test_a_pre_fixed_call_watcher_is_disabled_not_run(monkeypatch):
    """No fingerprint = set up before c98e0ac, when nothing was confirmed."""
    task, published = _registered(monkeypatch)
    del task["action"]["fingerprint"]
    watcher._fire(task["action"], "Battery is at 9%.", task=task)
    assert task["disabled"] and published[0].tool == ""
    assert "set it up again" in published[0].query.lower()


def test_a_changed_tool_policy_disables_the_watcher(monkeypatch):
    task, published = _registered(monkeypatch, fingerprint="stale-schema-or-class")
    watcher._fire(task["action"], "", task=task)
    assert "changed since you confirmed" in task["disabled"]
    assert published[0].tool == "", "the stale call must not be dispatched"


def test_a_disabled_watcher_is_skipped(monkeypatch):
    task, published = _registered(monkeypatch)
    task["disabled"] = "x"
    calls = []
    monkeypatch.setattr(watcher, "_check_task", calls.append)
    import threading
    watcher.running = True
    t = threading.Thread(target=watcher._loop, daemon=True); t.start()
    import time; time.sleep(0.3); watcher.running = False; t.join(6)
    assert calls == []


def test_an_unchanged_watcher_still_fires(monkeypatch):
    task, published = _registered(monkeypatch)
    watcher._fire(task["action"], "Battery is at 9%.", task=task)
    assert "disabled" not in task and published[0].tool == "find_file"
