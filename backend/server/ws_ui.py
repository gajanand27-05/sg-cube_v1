import asyncio
import json
import logging
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
    ProactiveEvent,
    SelfHealingEvent,
    SpokenResponse,
    TokenStreamEvent,
    WakeHeard,
    SystemStatsEvent,
)

log = logging.getLogger(__name__)

EVENT_TYPES = [
    StateChangedEvent,
    WakeHeard,
    CommandTranscribed,
    IntentResolved,
    Executed,
    SpokenResponse,
    TokenStreamEvent,
    ConfidenceEvent,
    SelfHealingEvent,
    InternalAgentEvent,
    AgentThinkingEvent,
    ClipboardChangedEvent,
    HandoverEvent,
    ProactiveEvent,
    SystemStatsEvent,
]


class WebUIManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._setup_event_bridge()

    def _setup_event_bridge(self):
        for event_type in EVENT_TYPES:
            bus.subscribe(event_type, self._broadcast_event)

    def _broadcast_event(self, event: Any):
        data = {
            "type": type(event).__name__,
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
            return event.model_dump()
        if hasattr(event, "__dict__"):
            d = event.__dict__.copy()
            if "score" in d and hasattr(d["score"], "__dict__"):
                d["score"] = d["score"].__dict__
            return d
        return {"data": str(event)}


manager = WebUIManager()
