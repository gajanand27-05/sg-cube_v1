"""YOLOv8n obstacle detection on phone camera frames — VisionClaw Phase 2.

Consumes the JPEG frames the phone streams to /ws/phone_stream, finds
navigation-relevant objects, and publishes ObstacleEvent(label, direction,
distance, priority) for the HUD; critical obstacles are spoken aloud in
navigate mode.

Design constraints from the plan:
  * CPU-only, yolov8n (~6MB), inference well under the 500ms frame interval.
  * conf > 0.5 model-side; publishing requires the SAME label+direction in two
    consecutive processed frames (2-frame confirmation against flicker).
  * Never blocks the WS receive loop — inference runs in the default executor,
    and a frame arriving while one is in flight is simply skipped.

ponytail: distance comes from the pinhole model with hardcoded real-world
object heights and an assumed focal length of 1.0 * frame_height (~55deg
vertical FOV, typical phone main camera). Real hardware needs calibration —
treat distances as coarse ("about 2 meters"), not measurements.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import ObstacleEvent

log = logging.getLogger(__name__)

# COCO label -> typical real-world height in meters (distance estimation).
KNOWN_HEIGHTS = {
    "person": 1.70,
    "bicycle": 1.00,
    "car": 1.45,
    "motorcycle": 1.10,
    "bus": 3.00,
    "truck": 3.00,
    "dog": 0.50,
    "cat": 0.30,
    "chair": 0.90,
    "bench": 0.50,
    "traffic light": 0.75,
    "stop sign": 0.75,
}
# Labels that can hurt you -> critical when close.
MOVING_HAZARDS = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "dog"}
CRITICAL_DISTANCE_M = 2.5
MODEL_CONF = 0.50
SPEAK_COOLDOWN_S = 4.0
_FOCAL_FACTOR = 1.0  # f_px ≈ frame_height * this; see ponytail note above


@dataclass
class Obstacle:
    label: str
    direction: str      # "left" | "straight" | "right"
    distance_m: float
    confidence: float
    priority: str       # "critical" | "warning"


_model = None


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO("yolov8n.pt")  # downloads once (~6MB) on first use
        log.info("YOLOv8n loaded for obstacle detection")
    return _model


def detect(jpeg: bytes) -> list[Obstacle]:
    """Run YOLO on one JPEG frame. Blocking (~40-150ms CPU) — call off-loop."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    frame_h, frame_w = img.shape[:2]
    results = _get_model()(img, conf=MODEL_CONF, verbose=False)

    out: list[Obstacle] = []
    for r in results:
        names = r.names
        for box in r.boxes:
            label = names[int(box.cls[0])]
            if label not in KNOWN_HEIGHTS:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            cx = (x1 + x2) / 2
            direction = "left" if cx < frame_w / 3 else "right" if cx > 2 * frame_w / 3 else "straight"
            box_h = max(1.0, y2 - y1)
            distance = KNOWN_HEIGHTS[label] * (_FOCAL_FACTOR * frame_h) / box_h
            priority = (
                "critical"
                if label in MOVING_HAZARDS and distance < CRITICAL_DISTANCE_M
                else "warning"
            )
            out.append(Obstacle(
                label=label,
                direction=direction,
                distance_m=round(distance, 1),
                confidence=round(float(box.conf[0]), 2),
                priority=priority,
            ))
    return out


class DetectionRunner:
    """Per-frame orchestration: skip-if-busy, 2-frame confirmation, event
    publishing, spoken alerts with cooldown. One instance per process."""

    def __init__(self):
        self._busy = False
        self._prev: set[tuple[str, str]] = set()  # (label, direction) last frame
        self._last_spoken: dict[str, float] = {}
        self.last_latency_ms: float = 0.0

    async def submit(self, jpeg: bytes, mode: str) -> None:
        """Called from the WS loop for every accepted frame. Never blocks."""
        if mode not in ("navigate", "scan"):
            return
        if self._busy:
            return  # a frame is being processed; this one is redundant at 2fps
        self._busy = True
        try:
            t0 = time.monotonic()
            loop = asyncio.get_running_loop()
            obstacles = await loop.run_in_executor(None, detect, jpeg)
            self.last_latency_ms = round((time.monotonic() - t0) * 1000, 1)

            current = {(o.label, o.direction) for o in obstacles}
            confirmed = [o for o in obstacles if (o.label, o.direction) in self._prev]
            self._prev = current

            bus = get_bus()
            for o in confirmed:
                bus.publish(
                    ObstacleEvent(
                        label=o.label,
                        direction=o.direction,
                        distance_m=o.distance_m,
                        confidence=o.confidence,
                        priority=o.priority,
                    ),
                    priority=Priority.HIGH,
                )
            if mode == "navigate":
                self._maybe_speak(confirmed)
        except Exception as e:
            log.error("Obstacle detection failed: %s", e)
        finally:
            self._busy = False

    def _maybe_speak(self, confirmed: list[Obstacle]) -> None:
        """Speak the nearest critical obstacle, per-label cooldown. Plan rule:
        terse and certain — 'Person ahead. 2 meters.' — never hedged."""
        critical = [o for o in confirmed if o.priority == "critical"]
        if not critical:
            return
        o = min(critical, key=lambda x: x.distance_m)
        now = time.monotonic()
        if now - self._last_spoken.get(o.label, 0.0) < SPEAK_COOLDOWN_S:
            return
        self._last_spoken[o.label] = now
        where = {"left": "on your left", "right": "on your right", "straight": "ahead"}[o.direction]
        meters = max(1, round(o.distance_m))
        try:
            from backend.ai_modules.speech import tts_piper
            tts_piper.speak(f"{o.label} {where}. {meters} meters.")
        except Exception as e:
            log.warning("Obstacle alert TTS failed: %s", e)


detection_runner = DetectionRunner()
