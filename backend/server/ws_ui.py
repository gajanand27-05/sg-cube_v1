import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from backend.core.events import bus
from backend.core.state import StateChangedEvent
from backend.daemon.ui_events import (
    AgentThinkingEvent,
    ClipboardChangedEvent,
    CommandTranscribed,
    ConfidenceEvent,
    Executed,
    HandoverEvent,
    IntentResolved,
    InternalAgentEvent,
    MemoryHitEvent,
    ProactiveEvent,
    SelfHealingEvent,
    SpokenResponse,
    SystemStatsEvent,
    TokenStreamEvent,
    ToolFinishedEvent,
    ToolStartedEvent,
    VisionUpdateEvent,
    WakeHeard,
)

log = logging.getLogger(__name__)

# PascalCase class name -> snake_case wire type
TYPE_MAP: dict[type, str] = {
    StateChangedEvent: "state_changed",
    WakeHeard: "wake_heard",
    CommandTranscribed: "command_transcribed",
    IntentResolved: "intent_resolved",
    Executed: "tool_finished",
    SpokenResponse: "spoken_response",
    TokenStreamEvent: "token_stream",
    ConfidenceEvent: "confidence",
    SelfHealingEvent: "self_healing",
    InternalAgentEvent: "agent_status",
    AgentThinkingEvent: "agent_thinking",
    ClipboardChangedEvent: "clipboard_changed",
    HandoverEvent: "handover",
    ProactiveEvent: "proactive",
    SystemStatsEvent: "system_stats",
    ToolStartedEvent: "tool_started",
    ToolFinishedEvent: "tool_finished",
    MemoryHitEvent: "memory_hit",
    VisionUpdateEvent: "vision_update",
}

EVENT_TYPES = list(TYPE_MAP.keys())


class UIEventManager:
    """Subscribes to every EventBus event and broadcasts JSON to all connected Web UI clients.

    Each message shape:
    {
      "type": "command_transcribed",
      "timestamp": "2026-06-21T14:30:00.123456+00:00",
      "payload": { ... }
    }
    """

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._setup_event_bridge()

    def _setup_event_bridge(self):
        for event_type in EVENT_TYPES:
            bus.subscribe(event_type, self._broadcast_event)

    def _broadcast_event(self, event: Any):
        wire_type = TYPE_MAP.get(type(event), type(event).__name__)
        data = {
            "type": wire_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": self._serialize(event),
        }
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.broadcast(data))
            )

    async def broadcast(self, data: dict):
        if not self._connections:
            return
        message = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    async def connect(self, ws: WebSocket):
        if not self._loop:
            self._loop = asyncio.get_running_loop()
        await ws.accept()
        self._connections.append(ws)
        log.info(f"Web UI client connected ({len(self._connections)} total)")

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)
            log.info(f"Web UI client disconnected ({len(self._connections)} remaining)")

    def _serialize(self, event: Any) -> dict:
        if hasattr(event, "model_dump"):
            d = event.model_dump()
        elif hasattr(event, "__dict__"):
            d = event.__dict__.copy()
            if "score" in d and hasattr(d["score"], "__dict__"):
                d["score"] = d["score"].__dict__
        else:
            return {"data": str(event)}

        # Flatten nested metrics for convenience
        if "metrics" in d and hasattr(d["metrics"], "__dict__"):
            for k, v in d["metrics"].__dict__.items():
                d[f"metric_{k}"] = v
            del d["metrics"]

        return d


manager = UIEventManager()
