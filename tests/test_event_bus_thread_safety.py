"""Audit: AsyncEventBus.publish() is called from foreign threads (voice loop,
telemetry loop, wake-word listener) but pushed into an asyncio.Queue with a bare
put_nowait. asyncio.Queue is not thread-safe: the wakeup for a parked get() is
scheduled with loop.call_soon, which does not wake a loop blocked in select()
when called off-thread. The wakeup therefore sat in _ready until the loop woke
for some other reason — here, _worker's own timeout=0.5 poll.

This test measures cross-thread delivery latency. Against the pre-fix publish()
it is ~0.4-0.5s (one full worker poll); with loop.call_soon_threadsafe it is
sub-millisecond.
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.events import AsyncEventBus, Priority


def _run(coro):
    """asyncio.run, but leaves a current event loop installed on the thread.

    asyncio.run() calls set_event_loop(None) on the way out, and tests that
    still use the deprecated asyncio.get_event_loop() then fail depending on
    collection order. Keep the blast radius inside this file.
    """
    try:
        return asyncio.run(coro)
    finally:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())


class _Ping:
    def __init__(self):
        self.sent_at = 0.0


def _run_cross_thread_publish(priority: Priority) -> float:
    """Publish one event from a non-loop thread; return delivery latency (s)."""
    latency: list[float] = []

    async def main():
        bus = AsyncEventBus(high_workers=1, normal_workers=1, low_workers=1)
        delivered = asyncio.Event()

        async def on_ping(ev: _Ping) -> None:
            latency.append(time.perf_counter() - ev.sent_at)
            delivered.set()

        bus.subscribe(_Ping, on_ping)
        await bus.start()
        # Let every worker reach wait_for(queue.get(), timeout=0.5) and park.
        await asyncio.sleep(0.1)

        def publisher():
            # The thread must not publish before the loop is actually blocked in
            # select() — otherwise the loop wakes for its own reasons and a lost
            # wakeup costs nothing, which is exactly how this bug stayed hidden.
            time.sleep(0.05)
            ev = _Ping()
            ev.sent_at = time.perf_counter()
            bus.publish(ev, priority=priority)

        threading.Thread(target=publisher, name="foreign-publisher").start()
        try:
            await asyncio.wait_for(delivered.wait(), timeout=5.0)
        finally:
            await bus.stop()

    _run(main())
    return latency[0]


def test_cross_thread_publish_is_not_stalled_by_worker_poll():
    for priority in (Priority.HIGH, Priority.NORMAL, Priority.LOW):
        seen = _run_cross_thread_publish(priority)
        # Measured: ~0.35s pre-fix (the remainder of the worker's 0.5s poll),
        # ~0.001s post-fix. 0.1s sits between the two regimes with room to spare.
        assert seen < 0.1, f"{priority.name} delivery took {seen:.3f}s — cross-thread wakeup lost"


def test_publish_before_start_is_buffered_not_dropped():
    """publish() used to log 'not started — dropping event' and discard. The
    voice thread can publish before the server loop calls start()."""
    bus = AsyncEventBus(high_workers=1, normal_workers=1, low_workers=1)
    got: list[_Ping] = []

    async def on_ping(ev: _Ping) -> None:
        got.append(ev)

    bus.subscribe(_Ping, on_ping)
    bus.publish(_Ping(), priority=Priority.HIGH)  # no loop exists yet

    async def main():
        await bus.start()
        for _ in range(50):
            if got:
                break
            await asyncio.sleep(0.02)
        await bus.stop()

    _run(main())
    assert got, "event published before start() was dropped"


def test_publish_from_loop_thread_still_works():
    """The same-thread fast path must not regress."""
    got: list[_Ping] = []

    async def main():
        bus = AsyncEventBus(high_workers=1, normal_workers=1, low_workers=1)

        async def on_ping(ev: _Ping) -> None:
            got.append(ev)

        bus.subscribe(_Ping, on_ping)
        await bus.start()
        bus.publish(_Ping(), priority=Priority.NORMAL)
        for _ in range(50):
            if got:
                break
            await asyncio.sleep(0.02)
        await bus.stop()

    _run(main())
    assert got, "same-thread publish was not delivered"
