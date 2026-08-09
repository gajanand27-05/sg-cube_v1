"""ObservabilityEngine — the numbers on the reliability panel must be true.

Three failure modes this pins down:

  * Double-counting. `report_tool_quality` used to fire twice for every tool
    Operator ran (once inside `Runtime.run_tool`, once in
    `OperatorAgent.execute_batch`) but only once — from Operator — when the tool
    crashed, because runtime's generic-exception branch never reported. One
    success plus one crash therefore booked 2 successes + 1 failure = 66.7%
    where the truth is 50%.
  * A success threshold of `confidence >= 100.0`, while real tools return
    60.0-98.0 on success. A tool that worked was filed as a failure.
  * Unbounded growth: `_current_metrics` was never popped, and `_latencies` /
    `_recall_scores` grew forever while being sum()-ed on every publish.
"""
import asyncio
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from backend.core.agents.operator import OperatorAgent
from backend.core.observability import (
    MAX_SAMPLES,
    MAX_TRACKED_REQUESTS,
    ObservabilityEngine,
)
from backend.core.runtime import Runtime
from backend.core.tools.registry import REGISTRY, ToolResult, tool


class _CapturingBus:
    """Stand-in for the async event bus — the real one only delivers to
    subscribers once its workers are running, which no unit test does."""

    def __init__(self):
        self.events = []

    def publish(self, event, *_a, **_kw):
        self.events.append(event)


@pytest.fixture
def engine_and_bus(monkeypatch):
    """A private engine + bus, so session-global counters can't skew asserts."""
    import backend.core.observability as obs_mod

    eng = obs_mod.ObservabilityEngine()
    bus = _CapturingBus()
    monkeypatch.setattr(obs_mod, "engine", eng)
    monkeypatch.setattr(obs_mod, "get_bus", lambda: bus)
    return eng, bus


@pytest.fixture
def probe_tools():
    """Register a succeeding tool (realistic sub-100 confidence) and a crashing
    one, then unregister them so the global REGISTRY isn't polluted."""

    @tool
    def obs_probe_ok():
        """Succeeds with the confidence a real tool actually reports."""
        return ToolResult.success("done", confidence=95.0)

    @tool
    def obs_probe_crash():
        """Raises — exercises run_tool's generic-exception branch."""
        raise RuntimeError("boom")

    try:
        yield
    finally:
        REGISTRY.pop("obs_probe_ok", None)
        REGISTRY.pop("obs_probe_crash", None)


# ── success rate ──────────────────────────────────────────────────────

def test_one_success_one_crash_is_fifty_percent(engine_and_bus, probe_tools):
    """The regression proof. Against the pre-fix tree this asserts 66.7%."""
    eng, bus = engine_and_bus

    asyncio.run(OperatorAgent().execute_batch(
        [{"name": "obs_probe_ok", "args": {}},
         {"name": "obs_probe_crash", "args": {}}],
        request_id="req-1",
    ))

    assert eng._total_tools == 2, "each tool call must be counted exactly once"
    assert eng._successful_tools == 1

    confidences = [e for e in bus.events if hasattr(e, "metrics")]
    assert confidences, "no ConfidenceEvent published"
    assert confidences[-1].metrics.tool_success_rate == pytest.approx(50.0)


def test_success_below_full_confidence_still_counts_as_success(engine_and_bus, probe_tools):
    """confidence=95 is a success. The old `>= 100.0` gate called it a failure."""
    eng, _ = engine_and_bus

    asyncio.run(Runtime().run_tool(
        "obs_probe_ok", REGISTRY["obs_probe_ok"].func, {}, request_id="req-2"))

    assert (eng._total_tools, eng._successful_tools) == (1, 1)


def test_explicit_success_flag_overrides_the_score(engine_and_bus):
    """A blocked result can carry a high confidence ("confidently refused"), so
    status wins over score when the caller knows it."""
    eng, _ = engine_and_bus
    eng.report_tool_quality("r", 99.0, "Status: blocked", success=False)
    assert (eng._total_tools, eng._successful_tools) == (1, 0)


# ── request-id hygiene ────────────────────────────────────────────────

def test_timeout_reports_under_the_request_id_not_the_task_id(engine_and_bus):
    """The timeout path used to report under the internal task_id, orphaning a
    metrics bucket and emitting a ConfidenceEvent for an id the UI never saw."""
    _, bus = engine_and_bus

    async def sleeper():
        await asyncio.sleep(5)

    asyncio.run(Runtime().run_tool(
        "sleeper", sleeper, {}, timeout=0.1, request_id="req-timeout"))

    confidences = [e for e in bus.events if hasattr(e, "metrics")]
    assert confidences, "timeout produced no ConfidenceEvent"
    assert {e.request_id for e in confidences} == {"req-timeout"}


def test_report_latency_for_an_unseen_request_does_not_raise(engine_and_bus):
    """_publish_update indexed _current_metrics directly; report_latency for an
    id with no prior tool/ai report raised KeyError (swallowed by Operator's
    bare except, so the latency silently never landed)."""
    eng, bus = engine_and_bus
    eng.report_latency("never-seen", 1200)
    assert eng._latencies == [1.2]
    assert bus.events[-1].request_id == "never-seen"


# ── bounded growth ────────────────────────────────────────────────────

def test_per_request_buckets_are_bounded(engine_and_bus):
    eng, _ = engine_and_bus
    for i in range(MAX_TRACKED_REQUESTS * 3):
        eng.report_tool_quality(f"req-{i}", 100.0, "ok", success=True)

    assert len(eng._current_metrics) <= MAX_TRACKED_REQUESTS
    # The newest request is the one the UI is watching — it must survive.
    assert f"req-{MAX_TRACKED_REQUESTS * 3 - 1}" in eng._current_metrics


def test_sample_lists_are_bounded_and_keep_the_newest(engine_and_bus):
    eng, _ = engine_and_bus
    for i in range(MAX_SAMPLES + 50):
        eng.report_latency("req", i)
        eng.report_context_quality("req", float(i), "ctx")

    assert len(eng._latencies) == MAX_SAMPLES
    assert len(eng._recall_scores) == MAX_SAMPLES
    assert eng._recall_scores[-1] == float(MAX_SAMPLES + 49)
    # /diagnostics slices these (`_latencies[-50:]`) — must stay a real list.
    assert isinstance(eng._latencies, list)
