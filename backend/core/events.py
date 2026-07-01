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

    def publish(self, event: Any, priority: Priority = Priority.NORMAL) -> None:
        """Non-blocking publish — returns immediately.

        Called from sync contexts (voice thread, etc.).
        """
        if self._loop is None or self._loop.is_closed():
            log.warning("Event bus not started — dropping event")
            return

        # Thread-safe: put_nowait from sync context
        try:
            self._queues[priority].put_nowait(QueuedEvent(priority, event, type(event)))
        except asyncio.QueueFull:
            log.warning(f"Event queue full (priority={priority.name}) — dropping {type(event).__name__}")

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
    if bus is None:
        # Auto-initialize if not already initialized
        bus = AsyncEventBus()
        _initialized = True
    return bus