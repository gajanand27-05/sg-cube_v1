import asyncio
import json
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.core.auth.deps import _is_private_host  # noqa: F401  (re-exported for callers)
from backend.core.events import get_bus
from backend.core.state import AssistantState, StateChangedEvent
from backend.daemon.trigger import handle_wake, on_wake_detected
from backend.daemon.ui_events import (
    ClipboardChangedEvent,
    CommandTranscribed,
    ConfidenceEvent,
    Executed,
    HandoverEvent,
    IntentResolved,
    InternalAgentEvent,
    SelfHealingEvent,
    SpokenResponse,
    TokenStreamEvent,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/remote", tags=["remote"])


# 16kHz mono int16 PCM = 32000 B/s, so this is ~60s of speech — far past any
# real utterance. A client that streams binary and never sends end_of_speech
# would otherwise grow this bytearray until the process OOMs.
MAX_AUDIO_BUFFER_BYTES = 32_000 * 60


class RemoteConnection:
    def __init__(self, websocket: WebSocket, device_id: str):
        self.websocket = websocket
        self.device_id = device_id
        self.audio_buffer = bytearray()
        self.is_active = True
        self.codec = "pcm"  # Default
        self.is_local = self._check_local()

    def _check_local(self) -> bool:
        """Check if the device is on the local network."""
        if not self.websocket.client:
            return False
        return _is_private_host(self.websocket.client.host)

    async def send_json(self, data: dict):
        if self.is_active:
            try:
                await self.websocket.send_json(data)
            except Exception:
                self.is_active = False

    async def send_bytes(self, data: bytes):
        if self.is_active:
            try:
                # Hybrid Transport: If codec is Opus, we'd encode here.
                # For now, we transmit raw and let the client know the expected format.
                await self.websocket.send_bytes(data)
            except Exception:
                self.is_active = False


class RemoteManager:
    def __init__(self):
        self.active_connections: Dict[str, RemoteConnection] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # The bus instance this bridge is subscribed to, not a bool — see the
        # matching note in ws_ui.UIEventManager. init_event_bus() builds a NEW
        # bus on every call, so a bool latch leaves the bridge attached to a
        # discarded instance while every event silently goes nowhere.
        # Deliberately duplicated rather than shared: the two managers differ
        # in wire format and lifecycle, and one test covers both against drift.
        self._bridged_bus = None

    def _setup_event_bridge(self):
        """Bridge Desktop EventBus to all connected Android devices."""
        bus = get_bus()
        if self._bridged_bus is bus:
            return
        for event_type in [
            StateChangedEvent, CommandTranscribed, IntentResolved,
            Executed, SpokenResponse, TokenStreamEvent,
            ConfidenceEvent, SelfHealingEvent, InternalAgentEvent,
            ClipboardChangedEvent, HandoverEvent
        ]:
            bus.subscribe(event_type, self._broadcast_event)
        self._bridged_bus = bus

    def _broadcast_event(self, event):
        """Forward local event to remote clients as JSON."""
        data = {
            "type": type(event).__name__,
            "payload": self._serialize_event(event)
        }
        
        # Bridge sync EventBus (potentially from sub-threads) to async loop
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.broadcast(data))
            )
        else:
            log.debug(f"Skipping broadcast of {data['type']}: no active loop captured yet")

    async def broadcast(self, data: dict):
        for conn in list(self.active_connections.values()):
            await conn.send_json(data)

    def _serialize_event(self, event) -> dict:
        if hasattr(event, "model_dump"):
            return event.model_dump()
        if hasattr(event, "__dict__"):
            d = event.__dict__.copy()
            # Handle non-serializable ConfidenceScore if present
            if "score" in d and hasattr(d["score"], "__dict__"):
                d["score"] = d["score"].__dict__
            return d
        return {"data": str(event)}

    async def connect(self, websocket: WebSocket, device_id: str):
        # Rebind a dead loop, don't just fill an empty slot. _broadcast_event
        # falls into its else branch when the stored loop is not running and
        # logs "no active loop captured yet" at debug — so a replaced loop
        # stops every device event forever behind a message that says the
        # opposite of what happened.
        if self.loop is None or not self.loop.is_running():
            self.loop = asyncio.get_running_loop()

        # The bus->device bridge used to hang off _get_bus(), which nothing
        # ever called — so subscribe() never ran and a connected Android
        # client received zero events, silently. connect() is the reachable
        # path (same fix as ws_ui.UIEventManager.connect).
        self._setup_event_bridge()

        await websocket.accept()
        conn = RemoteConnection(websocket, device_id)
        self.active_connections[device_id] = conn
        
        transport = "PCM (Local)" if conn.is_local else "Opus Fallback (Remote)"
        log.info(f"Remote device connected: {device_id} via {transport}")
        
        # Negotiate initial codec
        await conn.send_json({
            "type": "ConfigSync",
            "payload": {
                "preferred_codec": "pcm" if conn.is_local else "opus",
                "is_local": conn.is_local
            }
        })
        return conn

    def disconnect(self, device_id: str):
        if device_id in self.active_connections:
            self.active_connections[device_id].is_active = False
            del self.active_connections[device_id]
            log.info(f"Remote device disconnected: {device_id}")

    async def broadcast_bytes_to_device(self, device_id: str, data: bytes):
        if device_id in self.active_connections:
            await self.active_connections[device_id].send_bytes(data)


manager = RemoteManager()


@router.websocket("/connect/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    # This socket can trigger wake/dispatch and write the host clipboard.
    # It carries no credential, so at minimum refuse peers outside the
    # LAN/loopback — otherwise binding APP_HOST=0.0.0.0 hands those
    # capabilities to any internet client.
    peer = websocket.client.host if websocket.client else ""
    if not _is_private_host(peer):
        log.warning(f"Rejected remote WS from non-private address {peer!r} (device_id={device_id!r})")
        await websocket.close(code=1008)
        return
    conn = await manager.connect(websocket, device_id)
    try:
        while True:
            # Protocol: Android sends either JSON (control) or Binary (audio)
            message = await websocket.receive()
            
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")
                
                if msg_type == "wake_word":
                    on_wake_detected()
                    conn.audio_buffer.clear()
                    
                elif msg_type == "end_of_speech":
                    if conn.audio_buffer:
                        audio_data = bytes(conn.audio_buffer)
                        conn.audio_buffer.clear()
                        # Run the trigger logic with device_id for remote routing
                        asyncio.create_task(asyncio.to_thread(handle_wake, audio_data, None, device_id))
                        
                elif msg_type == "interrupt":
                    from backend.core.agents.commander import commander
                    commander.interrupt()

                elif msg_type == "clipboard_sync":
                    text = data.get("payload", {}).get("text")
                    if text:
                        import pyperclip
                        from backend.daemon.clipboard_watcher import watcher as cb_watcher
                        cb_watcher.last_text = text
                        pyperclip.copy(text)
                        log.info(f"Remote clipboard sync: {len(text)} chars")

                elif msg_type == "set_codec":
                    codec = data.get("payload", {}).get("codec")
                    if codec in ["pcm", "opus"]:
                        conn.codec = codec
                        log.info(f"Device {device_id} switched to {codec}")

            elif "bytes" in message:
                # Accumulate audio chunks (PCM 16kHz)
                conn.audio_buffer.extend(message["bytes"])
                if len(conn.audio_buffer) > MAX_AUDIO_BUFFER_BYTES:
                    log.warning(
                        f"Device {device_id} exceeded {MAX_AUDIO_BUFFER_BYTES} B "
                        f"without end_of_speech — dropping buffer"
                    )
                    conn.audio_buffer.clear()

    except WebSocketDisconnect:
        manager.disconnect(device_id)
    except Exception as e:
        log.exception(f"Remote WebSocket error: {e}")
        manager.disconnect(device_id)
