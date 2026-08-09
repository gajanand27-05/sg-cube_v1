"""Async Event Bus with Priority Lanes — voice loop never blocks on callbacks."""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Type, TypeVar, Awaitable
import threading

T = TypeVar("T")

log = logging.getLogger(__name__)


class Priority(IntEnum):
    """Event priority — HIGH processed first, never blocked by lower."""
    HIGH = 0      # WakeDetected, CommandTranscribed, Interrupt, VoiceStateChange
    NORMAL = 1    # IntentResolved, Executed, ToolStarted, ToolFinished
    LOW = 2       # Telemetry, Logs, Analytics, MemoryWrites


@dataclass(order=True)
class QueuedEvent:
    """Event wrapper with priority for queue ordering."""
    priority: int
    event: Any = field(compare=False)
    event_type: Type = field(compare=False)


class AsyncEventBus:
    """Async event bus with priority queue and worker pool.

    Voice loop publishes → returns immediately.
    Workers process callbacks in priority order.
    """

    def __init__(
        self,
        high_workers: int = 2,
        normal_workers: int = 4,
        low_workers: int = 2,
        max_queue_size: int = 1000,
    ):
        self._subscribers: dict[Type, list[Callable[[Any], Awaitable[None] | None]]] = defaultdict(list)
        self._lock = threading.Lock()

        # Priority queues
        self._queues: dict[Priority, asyncio.Queue] = {
            Priority.HIGH: asyncio.Queue(maxsize=max_queue_size),
            Priority.NORMAL: asyncio.Queue(maxsize=max_queue_size),
            Priority.LOW: asyncio.Queue(maxsize=max_queue_size),
        }
        self._workers: dict[Priority, list[asyncio.Task]] = defaultdict(list)
        self._worker_counts = {
            Priority.HIGH: high_workers,
            Priority.NORMAL: normal_workers,
            Priority.LOW: low_workers,
        }
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, event_type: Type[T], callback: Callable[[T], Awaitable[None] | None]) -> None:
        """Register an async callback for an event type."""
        with self._lock:
            self._subscribers[event_type].append(callback)
            log.debug(f"Subscribed {callback.__name__} to {event_type.__name__}")

    def _enqueue(self, priority: Priority, item: "QueuedEvent") -> None:
        try:
            self._queues[priority].put_nowait(item)
        except asyncio.QueueFull:
            log.warning(f"Event queue full (priority={priority.name}) — dropping {type(item.event).__name__}")

    def publish(self, event: Any, priority: Priority = Priority.NORMAL) -> None:
        """Non-blocking publish — returns immediately. Safe from any thread.

        `asyncio.Queue` is *not* thread-safe. `put_nowait` wakes a parked
        `get()` via `loop.call_soon`, which only schedules on the loop's own
        thread — calling it from the voice thread leaves the wakeup sitting in
        `_ready` until the loop happens to wake for another reason. The
        `timeout=0.5` in `_worker` is what hid this, at the cost of up to 500ms
        of delivery latency per cross-thread event. So hop the loop properly.
        """
        item = QueuedEvent(priority, event, type(event))
        loop = self._loop

        if loop is None or loop.is_closed():
            # Not started yet (or already torn down): no workers are parked, so
            # there is no wakeup to schedule. Buffer it in the queue — a
            # pre-start event is delivered as soon as start() spawns workers.
            self._enqueue(priority, item)
            return

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            self._enqueue(priority, item)  # already on the bus loop's thread
        else:
            loop.call_soon_threadsafe(self._enqueue, priority, item)

    async def _worker(self, priority: Priority) -> None:
        """Process events from a specific priority queue."""
        queue = self._queues[priority]
        while self._running:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            event = item.event
            event_type = item.event_type

            with self._lock:
                subscribers = list(self._subscribers.get(event_type, []))

            if not subscribers:
                log.debug(f"No subscribers for {event_type.__name__}")
                continue

            for callback in subscribers:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        # Sync callback — run in executor to not block worker
                        await asyncio.get_event_loop().run_in_executor(None, callback, event)
                except Exception:
                    log.exception(f"Error in callback {callback.__name__} for {event_type.__name__}")

    async def start(self) -> None:
        """Start worker tasks on the current event loop."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()

        for priority, count in self._worker_counts.items():
            for _ in range(count):
                task = self._loop.create_task(self._worker(priority))
                self._workers[priority].append(task)

        log.info(f"Event bus started: HIGH={self._worker_counts[Priority.HIGH]}, "
                 f"NORMAL={self._worker_counts[Priority.NORMAL]}, LOW={self._worker_counts[Priority.LOW]}")

    async def stop(self) -> None:
        """Stop all workers and drain queues."""
        self._running = False
        for tasks in self._workers.values():
            for task in tasks:
                task.cancel()
        # Wait for cancellation
        all_tasks = [t for tasks in self._workers.values() for t in tasks]
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        log.info("Event bus stopped")


# Global instance
bus: AsyncEventBus | None = None
_initialized = False
_bus_lock = threading.Lock()


def init_event_bus(
    high_workers: int = 2,
    normal_workers: int = 4,
    low_workers: int = 2,
) -> AsyncEventBus:
    """Initialize global event bus."""
    global bus, _initialized
    bus = AsyncEventBus(high_workers, normal_workers, low_workers)
    _initialized = True
    return bus


def get_bus() -> AsyncEventBus:
    global bus, _initialized
    # Double-checked locking: publishers call this from several threads. An
    # unguarded check lets two of them each build a bus, and whichever loses the
    # assignment race keeps a handle to an orphan — its subscribers never see
    # events published on the winner.
    if bus is None:
        with _bus_lock:
            if bus is None:
                bus = AsyncEventBus()
                _initialized = True
    return bus