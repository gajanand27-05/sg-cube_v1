"""Context collection must not block the loop on work nothing reads.

`collect()` runs on the wake->first_token path, the hop that decides how fast
the assistant feels ("perceived latency is time-to-first-audio, not total").
Four memory lookups were correctly dispatched with asyncio.to_thread, then two
more collectors ran INLINE under the comment "(sync, fast)" — which is why they
went unexamined. Measured on this machine: _get_running_apps 13ms cold / 1.7ms
warm (psutil walks every process), _get_screen_objects 115ms cold / 15ms warm
(a Chroma query). Their whole cost landed on the critical path, serialized
ahead of tasks that were already in flight.

Neither field is read by the planner: its prompt renders only capabilities,
recent_conversation, long_term_memory and recent_events. They are populated for
consumers that may not exist, which is exactly the work you want overlapped
rather than blocking.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.context.builder import context_builder
from backend.core.context.types import RequestContext

SLOW_MS = 120


@pytest.fixture()
def slow_collectors(monkeypatch):
    """Make every collector cost real wall-clock, so serialization shows up as
    a sum and overlap shows up as a max."""
    def _slow(value):
        def _fn(*_args, **_kwargs):
            time.sleep(SLOW_MS / 1000)
            return value
        return _fn

    monkeypatch.setattr(context_builder, "_get_stm_context", _slow([]))
    monkeypatch.setattr(context_builder, "_get_ltm_context", _slow([]))
    monkeypatch.setattr(context_builder, "_get_timeline_context", _slow([]))
    monkeypatch.setattr(context_builder, "_get_screen_context", _slow([]))
    monkeypatch.setattr(context_builder, "_get_running_apps", _slow(["notepad"]))
    monkeypatch.setattr(context_builder, "_get_screen_objects", _slow([]))
    monkeypatch.setattr(context_builder, "_get_active_window", lambda *a, **k: None)


def test_collectors_run_concurrently_not_one_after_another(slow_collectors):
    """Six collectors at 120ms each: ~120ms overlapped, ~720ms serialized.
    The threshold sits far from both, so this measures the shape, not the
    machine."""
    t0 = time.perf_counter()
    asyncio.run(context_builder.collect(RequestContext(user_intent="hi", request_id="t1")))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < SLOW_MS * 3, (
        f"context collection took {elapsed_ms:.0f}ms for six {SLOW_MS}ms collectors — "
        "they are running serially; the inline ones belong in the gather"
    )


def test_the_previously_inline_collectors_still_reach_the_context(slow_collectors):
    """Overlapping them must not quietly drop their results — an empty list is
    exactly what a broken gather unpacking would produce."""
    ctx = asyncio.run(context_builder.collect(RequestContext(user_intent="hi", request_id="t2")))
    assert ctx.running_apps == ["notepad"], (
        f"running_apps came back {ctx.running_apps!r}; the gather results are "
        "unpacked positionally, so a reordering silently swaps fields"
    )
    assert ctx.screen_objects == []


def test_a_failing_collector_does_not_take_down_the_turn(monkeypatch, slow_collectors):
    """return_exceptions=True means a raising collector arrives as an Exception
    object. Without an isinstance check it would be assigned straight into the
    context and blow up later, far from the cause."""
    def _boom(*_a, **_k):
        raise RuntimeError("psutil exploded")

    monkeypatch.setattr(context_builder, "_get_running_apps", _boom)
    ctx = asyncio.run(context_builder.collect(RequestContext(user_intent="hi", request_id="t3")))
    assert ctx.running_apps == [], f"expected the failure to degrade to [], got {ctx.running_apps!r}"
