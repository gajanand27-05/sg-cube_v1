import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from backend.core.events import get_bus
from backend.core.state import StateChangedEvent
from backend.daemon.ui_events import (
    AgentCompletedEvent,
    AgentReasoningEvent,
    AgentThinkingEvent,
    AgentToolCallEvent,
    CanvasUpdateEvent,
    ClipboardChangedEvent,
    CommandTranscribed,
    ConfidenceEvent,
    Executed,
    HandoverEvent,
    IntentResolved,
    InternalAgentEvent,
    MemoryHitEvent,
    MemoryWriteFailedEvent,
    ProactiveEvent,
    ProviderDegradedEvent,
    SelfHealingEvent,
    SpeechInterruptedEvent,
    SpokenResponse,
    STTPartialEvent,
    SystemStatsEvent,
    TokenStreamEvent,
    ToolFinishedEvent,
    ToolStartedEvent,
    VisionUpdateEvent,
    WakeHeard,
    AIMetricsEvent,
)

log = logging.getLogger(__name__)

# PascalCase class name -> snake_case wire type
TYPE_MAP: dict[type, str] = {
    StateChangedEvent: "state_changed",
    WakeHeard: "wake_heard",
    CommandTranscribed: "command_transcribed",
    IntentResolved: "intent_resolved",
    # Distinct from ToolFinishedEvent below: both used to map to
    # "tool_finished" despite carrying incompatible payloads (command/message/
    # reason/confidence here vs tool_name/result/error there), so a consumer
    # got randomly-shaped objects depending on which fired.
    Executed: "executed",
    SpokenResponse: "spoken_response",
    STTPartialEvent: "stt_partial",
    TokenStreamEvent: "token_stream",
    ConfidenceEvent: "confidence",
    SelfHealingEvent: "self_healing",
    InternalAgentEvent: "agent_status",
    AgentThinkingEvent: "agent_thinking",
    AgentReasoningEvent: "agent_reasoning",
    AgentToolCallEvent: "agent_tool_call",
    AgentCompletedEvent: "agent_completed",
    ClipboardChangedEvent: "clipboard_changed",
    HandoverEvent: "handover",
    ProactiveEvent: "proactive",
    SystemStatsEvent: "system_stats",
    AIMetricsEvent: "ai_metrics",
    ToolStartedEvent: "tool_started",
    ToolFinishedEvent: "tool_finished",
    MemoryHitEvent: "memory_hit",
    MemoryWriteFailedEvent: "memory_write_failed",
    VisionUpdateEvent: "vision_update",
    CanvasUpdateEvent: "canvas_update",
    SpeechInterruptedEvent: "speech_interrupted",
    ProviderDegradedEvent: "provider_degraded",
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
        # The bus instance the bridge is subscribed to, not a bool. A bool
        # latch means that if the global bus is ever REPLACED — init_event_bus()
        # constructs a fresh one every call — the bridge stays subscribed to the
        # discarded instance and every HUD event vanishes, permanently, with
        # nothing logged. Comparing instances re-subscribes instead.
        self._bridged_bus = None

    def _setup_event_bridge(self):
        bus = get_bus()
        if self._bridged_bus is bus:
            return
        for event_type in EVENT_TYPES:
            bus.subscribe(event_type, self._broadcast_event)
        self._bridged_bus = bus

    def _broadcast_event(self, event: Any):
        # Lazy setup on first event
        if self._bridged_bus is not get_bus():
            self._setup_event_bridge()
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
        # Rebind when the stored loop is gone. _broadcast_event gates on
        # `self._loop.is_running()` and simply returns when it is False, so a
        # stale loop here silently stops every HUD event forever with nothing
        # logged on either side. Binding once assumed the process has exactly
        # one loop for its whole life — true of a plain uvicorn run, false
        # after a reload and false for any second loop.
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.get_running_loop()
        # Ensure bus→WS bridge exists. _broadcast_event was the only
        # caller and it can't fire until the subscription exists — so this
        # was the reachable path that actually sets it up.
        if self._bridged_bus is not get_bus():
            self._setup_event_bridge()
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

        return self._to_jsonable(d)

    @staticmethod
    def _to_jsonable(v: Any) -> Any:
        """Recursively convert dataclass instances (and their nested fields)
        into plain dicts/lists so the payload is JSON-serializable. Needed
        now that MemoryHitEvent/VisionUpdateEvent carry nested dataclasses."""
        if hasattr(v, "__dataclass_fields__"):
            return {k: UIEventManager._to_jsonable(val) for k, val in v.__dict__.items()}
        if isinstance(v, (list, tuple)):
            return [UIEventManager._to_jsonable(x) for x in v]
        if isinstance(v, dict):
            return {k: UIEventManager._to_jsonable(val) for k, val in v.items()}
        return v


_manager: UIEventManager | None = None


def get_manager() -> UIEventManager:
    global _manager
    if _manager is None:
        _manager = UIEventManager()
    return _manager
