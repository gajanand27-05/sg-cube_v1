import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Type, TypeVar

T = TypeVar("T")

log = logging.getLogger(__name__)


class EventBus:
    """A simple thread-safe in-memory pub/sub event bus."""

    def __init__(self):
        self._subscribers: dict[Type, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: Type[T], callback: Callable[[T], None]) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)
            log.debug(f"Subscribed {callback.__name__} to {event_type.__name__}")

    def publish(self, event: Any) -> None:
        event_type = type(event)
        with self._lock:
            subscribers = list(self._subscribers.get(event_type, []))

        if not subscribers:
            log.debug(f"No subscribers for event: {event_type.__name__}")
            return

        for callback in subscribers:
            try:
                # Run callbacks in the publisher's thread for now.
                # If we need true async, we can wrap this in threading.Thread.
                callback(event)
            except Exception:
                log.exception(f"Error in event callback {callback.__name__} for {event_type.__name__}")


# Global instance for easy access across the daemon
bus = EventBus()
