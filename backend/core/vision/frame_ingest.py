"""Phone frame ingestion and throttling.

Receives JPEG frames (raw bytes) from the phone WS, throttles to 2fps max,
keeps the latest frame in memory for the HUD to fetch over HTTP, and
publishes a lightweight PhoneFrameEvent (metadata only — pixels never ride
the event bus).

The phone page already captures at <=800px / 60% JPEG quality, so no
server-side resize happens here.
ponytail: single latest-frame buffer, no history — Phase 2 (YOLO) consumes
frames as they arrive; a ring buffer is the upgrade path if detection needs
lookback.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import PhoneFrameEvent

log = logging.getLogger(__name__)

MAX_FRAME_BYTES = 2 * 1024 * 1024  # reject anything bigger — not a camera frame


@dataclass
class FrameMeta:
    """Metadata of the most recent accepted frame."""
    frame_id: int
    timestamp: float   # server receive time (epoch)
    mode: str
    size_bytes: int
    fps_received: float


class FrameIngestor:
    """Throttles phone frames, keeps the latest, publishes events.

    Thread-safe: the WS receive loop writes, HTTP GET /vision/phone_frame
    reads from uvicorn worker threads.
    """

    def __init__(self, max_fps: float = 2.0):
        self.max_fps = max_fps
        self.min_interval = 1.0 / max_fps
        self._lock = threading.Lock()
        self._last_accept: float = 0.0
        self._frame_count: int = 0
        self._dropped_count: int = 0
        self._latest: Optional[bytes] = None
        self._latest_meta: Optional[FrameMeta] = None
        # timestamps of recently *offered* frames, for a real received-fps figure
        self._recent_offers: list[float] = []

    def ingest_frame(self, jpeg: bytes, mode: str = "idle") -> Optional[FrameMeta]:
        """Accept one JPEG frame. Returns its meta, or None if throttled/rejected."""
        if not jpeg:
            return None
        if len(jpeg) > MAX_FRAME_BYTES:
            log.warning("phone frame rejected: %d bytes > %d cap", len(jpeg), MAX_FRAME_BYTES)
            return None

        now = time.monotonic()
        with self._lock:
            self._recent_offers.append(now)
            cutoff = now - 3.0
            self._recent_offers = [t for t in self._recent_offers if t > cutoff]
            fps_received = len(self._recent_offers) / 3.0

            if now - self._last_accept < self.min_interval:
                self._dropped_count += 1
                return None

            self._last_accept = now
            self._frame_count += 1
            meta = FrameMeta(
                frame_id=self._frame_count,
                timestamp=time.time(),
                mode=mode,
                size_bytes=len(jpeg),
                fps_received=round(fps_received, 2),
            )
            self._latest = jpeg
            self._latest_meta = meta

        get_bus().publish(
            PhoneFrameEvent(
                frame_id=meta.frame_id,
                timestamp=meta.timestamp,
                mode=meta.mode,
                fps_received=meta.fps_received,
            ),
            priority=Priority.HIGH,
        )
        return meta

    def latest_frame(self) -> tuple[Optional[bytes], Optional[FrameMeta]]:
        with self._lock:
            return self._latest, self._latest_meta

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "frames_processed": self._frame_count,
                "frames_dropped": self._dropped_count,
                "max_fps": self.max_fps,
            }


# Global instance — one phone per session (see VISION_INTEGRATION_PLAN risk matrix)
frame_ingestor = FrameIngestor(max_fps=2.0)
