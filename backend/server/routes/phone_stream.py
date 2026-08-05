"""Phone camera WebSocket endpoint.

Receives JPEG frames from phone, publishes PhoneFrameEvent, sends health updates.

Phase 1 of VisionClaw integration.
"""
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.events import get_bus
from backend.core.vision.frame_ingest import frame_ingestor
from backend.daemon.ui_events import VisionHealthEvent, ModeChangeEvent

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["phone_stream"])


@router.websocket("/phone_stream")
async def phone_stream_ws_endpoint(ws: WebSocket):
    """Accept phone camera frames via WebSocket.

    Expected frame format:
    {
      "type": "frame",
      "id": 1,
      "timestamp": 1234567890.123,
      "mode": "navigate"  # or "scan" | "read" | "idle"
    }

    Control messages:
    {
      "type": "mode_change",
      "mode": "navigate"  # or "scan" | "read" | "idle"
    }
    """
    await ws.accept()
    log.info("Phone stream client connected")

    # Stats for health updates
    frame_count = 0
    last_health = time.monotonic()

    try:
        async for msg in ws.iter_text():
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                log.warning(f"Invalid JSON from phone: {msg[:200]}")
                continue

            msg_type = data.get("type")

            if msg_type == "frame":
                frame_id = data.get("id", 0)
                timestamp = data.get("timestamp", time.time())
                mode = data.get("mode", "idle")

                # Ingest frame (throttles to 2fps)
                frame_info = await frame_ingestor.ingest_frame(
                    frame_id=frame_id,
                    timestamp=timestamp,
                    mode=mode,
                )

                frame_count += 1
                if frame_info is None:
                    log.debug(f"Frame {frame_id} throttled (dps)")
                else:
                    log.debug(f"Frame {frame_id} ingested: {frame_info.fps} fps")

            elif msg_type == "mode_change":
                mode = data.get("mode", "idle")
                bus = get_bus()
                bus.publish(ModeChangeEvent(mode=mode))
                log.info(f"Mode changed to: {mode}")

            elif msg_type == "health":
                # Send health update periodically
                fps_received = 0.0
                stats = frame_ingestor.stats
                fps_processed = stats["frames_processed"]
                dropped = stats["frames_dropped"]

                total_frames = fps_processed + dropped
                fps_received = total_frames / max(1.0, time.monotonic() - last_health)

                health_event = VisionHealthEvent(
                    fps_received=fps_received,
                    fps_processed=max(0.0, fps_received),
                    detector_latency_ms=0.0,
                    tts_queue_depth=0,
                    dropped_frames=dropped,
                    mode="idle",
                )

                bus = get_bus()
                bus.publish(health_event)
                last_health = time.monotonic()

            else:
                log.warning(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        log.info("Phone stream client disconnected")
    except Exception as e:
        log.error(f"Phone stream error: {e}")

    finally:
        # Cleanup on disconnect
        log.info(f"Phone stream session ended: {frame_count} frames total")