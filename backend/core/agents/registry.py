import logging
import threading
from datetime import datetime

from backend.core.events import get_bus
from backend.daemon.ui_events import (
    InternalAgentEvent,
    AgentThinkingEvent,
    AgentReasoningEvent,
    AgentToolCallEvent,
    AgentCompletedEvent,
)

log = logging.getLogger(__name__)


class AgentRegistry:
    """Tracks full agent lifecycle state by subscribing to agent events."""

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, dict] = {}
        self._subscribed = False

    def _subscribe(self):
        bus = get_bus()
        bus.subscribe(InternalAgentEvent, self._on_agent_event)
        bus.subscribe(AgentThinkingEvent, self._on_thinking_event)
        bus.subscribe(AgentReasoningEvent, self._on_reasoning_event)
        bus.subscribe(AgentToolCallEvent, self._on_tool_event)
        bus.subscribe(AgentCompletedEvent, self._on_completed_event)
        self._subscribed = True
        log.debug("AgentRegistry subscribed to event bus")

    def _ensure_subscribed(self):
        if not self._subscribed:
            self._subscribe()

    def _ensure(self, agent_name: str) -> dict:
        return self._agents.setdefault(agent_name, {
            "name": agent_name,
            "status": "standby",
            "current_action": None,
            "is_thinking": False,
            "reasoning": "",
            "tools": [],
            "confidence": 100.0,
            "latency_ms": 0,
            "last_seen": datetime.now().isoformat(),
            "details": {},
        })

    def _on_agent_event(self, event: InternalAgentEvent):
        self._ensure_subscribed()
        with self._lock:
            e = self._ensure(event.agent_name)
            e["current_action"] = event.action
            e["details"] = event.details
            e["last_seen"] = datetime.now().isoformat()

    def _on_thinking_event(self, event: AgentThinkingEvent):
        self._ensure_subscribed()
        with self._lock:
            e = self._ensure(event.agent_name)
            e["is_thinking"] = event.is_thinking
            e["status"] = "thinking" if event.is_thinking else "standby"
            e["last_seen"] = datetime.now().isoformat()

    def _on_reasoning_event(self, event: AgentReasoningEvent):
        self._ensure_subscribed()
        with self._lock:
            e = self._ensure(event.agent_name)
            e["reasoning"] = event.reasoning
            e["status"] = "thinking"
            e["last_seen"] = datetime.now().isoformat()

    def _on_tool_event(self, event: AgentToolCallEvent):
        self._ensure_subscribed()
        with self._lock:
            e = self._ensure(event.agent_name)
            tool_entry = {
                "tool": event.tool,
                "args": event.args,
                "result": event.result,
                "latency_ms": event.latency_ms,
                "timestamp": datetime.now().isoformat(),
            }
            e.setdefault("tools", []).append(tool_entry)
            e["current_action"] = f"Tool: {event.tool}"
            e["last_seen"] = datetime.now().isoformat()

    def _on_completed_event(self, event: AgentCompletedEvent):
        self._ensure_subscribed()
        with self._lock:
            e = self._ensure(event.agent_name)
            e["status"] = event.status
            e["confidence"] = event.confidence
            e["latency_ms"] = event.latency_ms
            e["summary"] = event.summary
            e["is_thinking"] = False
            e["current_action"] = None
            e["last_seen"] = datetime.now().isoformat()

    def get_status(self) -> list[dict]:
        self._ensure_subscribed()
        with self._lock:
            return list(self._agents.values())

    def get_active_agent(self) -> str | None:
        self._ensure_subscribed()
        with self._lock:
            for name, info in self._agents.items():
                if info.get("is_thinking"):
                    return name
            return None


_registry = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
