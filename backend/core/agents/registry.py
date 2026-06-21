import logging
import threading
from datetime import datetime

from backend.core.events import bus
from backend.daemon.ui_events import InternalAgentEvent, AgentThinkingEvent

log = logging.getLogger(__name__)


class AgentRegistry:
    """Tracks agent state by subscribing to agent events on the bus."""

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, dict] = {}
        self._subscribe()

    def _subscribe(self):
        bus.subscribe(InternalAgentEvent, self._on_agent_event)
        bus.subscribe(AgentThinkingEvent, self._on_thinking_event)

    def _on_agent_event(self, event: InternalAgentEvent):
        with self._lock:
            entry = self._agents.setdefault(event.agent_name, {
                "name": event.agent_name,
                "status": "standby",
                "current_action": None,
                "is_thinking": False,
                "last_seen": datetime.now().isoformat(),
            })
            entry["current_action"] = event.action
            entry["details"] = event.details
            entry["last_seen"] = datetime.now().isoformat()

    def _on_thinking_event(self, event: AgentThinkingEvent):
        with self._lock:
            entry = self._agents.setdefault(event.agent_name, {
                "name": event.agent_name,
                "status": "standby",
                "current_action": None,
                "is_thinking": False,
                "last_seen": datetime.now().isoformat(),
            })
            entry["is_thinking"] = event.is_thinking
            entry["status"] = "thinking" if event.is_thinking else "standby"
            entry["last_seen"] = datetime.now().isoformat()

    def get_status(self) -> list[dict]:
        with self._lock:
            return list(self._agents.values())

    def get_active_agent(self) -> str | None:
        with self._lock:
            for name, info in self._agents.items():
                if info.get("status") == "thinking" or info.get("current_action"):
                    return name
            return None


registry = AgentRegistry()
