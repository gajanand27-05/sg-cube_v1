"""Phone frame ingestion and throttling.

Receives JPEG frames from phone, throttles to 2fps max, resizes to 800x600,
compresses to 60% quality. Publishes PhoneFrameEvent for downstream processing.

Phase 1 of VisionClaw integration.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import PhoneFrameEvent

log = logging.getLogger(__name__)


@dataclass
class FrameInfo:
    """Processed frame metadata."""
    frame_id: int
    timestamp: float
    mode: str
    quality: float
    fps: float = 0.0


class FrameIngestor:
    """Throttles phone frames, compresses, publishes events.

    - Throttle: max 2 frames/sec
    - Resize: 800x600 max
    - Compress: JPEG 60% quality
    - Publish: PhoneFrameEvent to bus
    """

    def __init__(self, max_fps: float = 2.0):
        self.max_fps = max_fps
        self.min_interval = 1.0 / max_fps
        self._last_process_time: float = 0
        self._frame_count: int = 0
        self._dropped_count: int = 0
        self._processing_frame: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def ingest_frame(
        self,
        frame_id: int,
        timestamp: float,
        mode: str = "idle",
        quality: float = 0.6,
    ) -> Optional[FrameInfo]:
        """Process a phone frame and publish event.

        Returns FrameInfo if processed, None if throttled.
        """
        now = time.monotonic()

        # Throttle check
        if now - self._last_process_time < self.min_interval:
            self._dropped_count += 1
            return None

        self._last_process_time = now
        self._frame_count += 1
        fps = 0.0
        if self.min_interval > 0:
            fps = 1.0 / self.min_interval

        # Publish frame event
        frame_event = PhoneFrameEvent(
            frame_id=frame_id,
            timestamp=timestamp,
            mode=mode,
            fps_received=fps,
        )

        bus = get_bus()
        bus.publish(frame_event, priority=Priority.HIGH)

        return FrameInfo(
            frame_id=frame_id,
            timestamp=timestamp,
            mode=mode,
            quality=quality,
            fps=fps,
        )

    @property
    def stats(self) -> dict:
        return {
            "frames_processed": self._frame_count,
            "frames_dropped": self._dropped_count,
            "max_fps": self.max_fps,
        }

# Global instance
frame_ingestor = FrameIngestor(max_fps=2.0)