import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from backend.core.events import bus

log = logging.getLogger(__name__)


@dataclass
class InternalAgentEvent:
    agent_name: str
    action: str
    details: dict[str, Any]


class BaseInternalAgent:
    """Base class for specialized reasoning roles."""

    def __init__(self, name: str):
        self.name = name

    def _emit(self, action: str, **kwargs):
        """Notify the system via the event bus."""
        event = InternalAgentEvent(agent_name=self.name, action=action, details=kwargs)
        bus.publish(event)
        log.debug(f"Agent {self.name} -> {action}: {kwargs}")
