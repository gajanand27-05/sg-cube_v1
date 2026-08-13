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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from backend.core.events import get_bus, Priority
from backend.core.vision.phone_session import registry
from backend.core.vision.vision_health import vision_health
from backend.daemon.ui_events import HapticEvent, ObstacleEvent, OcrReadEvent

log = logging.getLogger(__name__)

# Alerts play on their own thread, never on the caller's loop.
#
# tts_piper.speak() branches on asyncio.get_running_loop(): with a loop it
# schedules playback as a task on THAT loop, and _audio_player's stream.write()
# blocks for the length of the audio. submit() runs on the uvicorn loop, so the
# obvious call stalls the HTTP server and both WebSockets for every alert —
# exactly the trade T-tts-loop-globals refused. On a worker thread there is no
# running loop, so speak() takes its asyncio.run() path and owns its own loop,
# the same shape as the daemon's per-capture handle_wake.
#
# Dedicated single worker, not the default executor: detect() already runs
# there, and a 2s utterance must never occupy a slot detection needs. One
# worker also serializes alerts, so two criticals can't talk over each other.
_speech_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obstacle-tts")

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
# Plan: "haptic relay — WS sends vibrate when obstacle <1m". Deliberately much
# tighter than CRITICAL_DISTANCE_M: speech warns, a buzz means stop now.
HAPTIC_DISTANCE_M = 1.0
HAPTIC_COOLDOWN_S = 1.5   # shorter than speech — a buzz can repeat, a sentence can't
_FOCAL_FACTOR = 1.0  # f_px ≈ frame_height * this; see ponytail note above

# The pinhole estimate is distance = H * frame_h / box_h, and box_h can never
# exceed frame_h — so the SMALLEST distance the model can ever report is the
# object's own height H. For a person that is 1.70m, which put HAPTIC_DISTANCE_M
# (1.0) out of reach for every class except the dog, and CRITICAL_DISTANCE_M
# (2.5) out of reach for bus/truck (3.00). The alert was geometrically dead, not
# mis-wired. Physically: inside ~H the object stops fitting in frame, its bbox
# clips at the frame edges, box_h saturates, and the distance number bottoms out
# instead of continuing to fall.
#
# A box touching BOTH the top and bottom edge therefore means "taller than the
# view" = closer than its own height, and the number must be discarded rather
# than trusted. Report a fixed inside-arm's-reach value instead.
_CLIP_TOLERANCE_PX = 2.0
CLIPPED_DISTANCE_M = 0.5
# ponytail: a box clipped at only ONE edge (feet cut off — common with a tilted
# phone) still under-measures box_h, so its distance is an OVER-estimate of
# unknown size. Left as-is: it's an upper bound, and escalating on one edge
# would buzz for every distant pedestrian whose feet are out of frame. Upgrade
# path is real calibration + a ground-plane estimate, not another threshold.


@dataclass
class Obstacle:
    label: str
    direction: str      # "left" | "straight" | "right"
    distance_m: float
    confidence: float
    priority: str       # "critical" | "warning"
    clipped: bool = False   # bbox filled the frame vertically — closer than measurable


_model = None


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO("yolov8n.pt")  # downloads once (~6MB) on first use
        log.info("YOLOv8n loaded for obstacle detection")
    return _model


def detect(jpeg: bytes, all_labels: bool = False) -> list[Obstacle]:
    """Run YOLO on one JPEG frame. Blocking (~40-150ms CPU) — call off-loop.

    By default only the KNOWN_HEIGHTS classes come back: navigation needs a
    distance, and distance needs a known real-world height. `all_labels=True`
    keeps everything the model saw — used for "what do you see", where naming a
    laptop matters more than ranging it. Those carry distance_m=0.0 (meaning
    unknown, never "at your feet") and priority "info".
    """
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
            known = label in KNOWN_HEIGHTS
            if not known and not all_labels:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            cx = (x1 + x2) / 2
            direction = "left" if cx < frame_w / 3 else "right" if cx > 2 * frame_w / 3 else "straight"
            box_h = max(1.0, y2 - y1)
            clipped = y1 <= _CLIP_TOLERANCE_PX and y2 >= frame_h - _CLIP_TOLERANCE_PX
            if known:
                distance = (
                    CLIPPED_DISTANCE_M if clipped
                    else KNOWN_HEIGHTS[label] * (_FOCAL_FACTOR * frame_h) / box_h
                )
                priority = (
                    "critical"
                    if label in MOVING_HAZARDS and distance < CRITICAL_DISTANCE_M
                    else "warning"
                )
            else:
                distance = 0.0   # unknown — no height to range against
                priority = "info"
            out.append(Obstacle(
                label=label,
                direction=direction,
                distance_m=round(distance, 1),
                confidence=round(float(box.conf[0]), 2),
                priority=priority,
                clipped=clipped,
            ))
    return out


_WHERE = {"left": "on your left", "right": "on your right", "straight": "ahead"}


def describe(obstacles: list[Obstacle]) -> str:
    """One spoken sentence for a set of detections.

    Shared by the "what do you see" tool and scan mode so the assistant cannot
    describe the same scene two different ways depending on how it was asked.
    """
    if not obstacles:
        return "Nothing recognizable in view."
    grouped = Counter((o.label, o.direction) for o in obstacles)
    parts = [f"{label if n == 1 else str(n) + ' ' + label + 's'} {_WHERE[direction]}"
             for (label, direction), n in grouped.most_common()]
    out = ", ".join(parts) + "."
    # Only rangeable objects get a distance — a 0.0 "unknown" must never be
    # spoken as though the thing were at the user's feet.
    nearest = min((o for o in obstacles if o.distance_m > 0),
                  key=lambda o: o.distance_m, default=None)
    if nearest is not None:
        # A clipped box has no usable range — say so instead of inventing one.
        how_far = "very close" if nearest.clipped else f"about {max(1, round(nearest.distance_m))} meters"
        out += f" Nearest is the {nearest.label}, {how_far}."
    return out


class DetectionRunner:
    """Per-frame orchestration: skip-if-busy, 2-frame confirmation, event
    publishing, spoken alerts with cooldown. One instance per process."""

    def __init__(self):
        self._busy = False
        self._prev: set[tuple[str, str]] = set()  # (label, direction) last frame
        self._last_spoken: dict[str, float] = {}
        self._last_buzz: float = 0.0
        self._last_read_spoken: set[str] = set()  # dedup lines across read frames
        self._ocr_unavailable_announced = False
        self.last_latency_ms: float = 0.0
        self.detections_done: int = 0

    def reset(self) -> None:
        """Drop per-session state on phone disconnect. Without this the first
        frame of a new session can be 'confirmed' against the previous
        session's detections, and cooldowns carry over."""
        self._prev.clear()
        self._last_spoken.clear()
        self._last_buzz = 0.0
        self._last_read_spoken.clear()
        self._ocr_unavailable_announced = False
        self.detections_done = 0

    def _maybe_buzz(self, confirmed: list[Obstacle]) -> None:
        """Vibrate the phone when something is inside arm's reach.

        Runs even in silent mode — silence is about not speaking in public, and
        removing the alert entirely would leave a blind user in a public space
        with no warning at all.
        """
        close = [o for o in confirmed
                 if 0 < o.distance_m < HAPTIC_DISTANCE_M and o.label in MOVING_HAZARDS]
        if not close:
            return
        now = time.monotonic()
        if now - self._last_buzz < HAPTIC_COOLDOWN_S:
            return
        self._last_buzz = now
        pulses = 1 if any(o.priority == "critical" for o in close) else 2
        get_bus().publish(HapticEvent(pulses=pulses), priority=Priority.HIGH)
        # The bus event drives the HUD; the phone has to be told separately —
        # it is a WebSocket client, not a bus subscriber.
        registry.push_soon({"type": "command", "action": "vibrate", "pulses": pulses})

    async def submit(self, jpeg: bytes, mode: str) -> None:
        """Called from the WS loop for every accepted frame. Never blocks."""
        if mode == "read":
            await self._read_submit(jpeg)
            return
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
            self.detections_done += 1
            # The WS loop cannot report this: it create_task()s submit() and
            # never learns whether inference ran or returned early on _busy —
            # and that skip gap is exactly what fps_processed measures.
            vision_health.note_frame_processed(latency_ms=self.last_latency_ms)

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
                        clipped=o.clipped,
                    ),
                    priority=Priority.HIGH,
                )
            if mode == "navigate":
                self._maybe_buzz(confirmed)
                self._maybe_speak(confirmed)
        except Exception as e:
            log.error("Obstacle detection failed: %s", e)
        finally:
            self._busy = False

    async def _read_submit(self, jpeg: bytes) -> None:
        """Read mode: OCR each frame, speak only new lines."""
        from backend.core.vision.ocr_reader import OCRUnavailable, ocr_frame

        if self._busy:
            return
        self._busy = True
        try:
            t0 = time.monotonic()
            loop = asyncio.get_running_loop()
            try:
                lines = await loop.run_in_executor(None, ocr_frame, jpeg)
            except OCRUnavailable as e:
                # Say it once per session, then stop: the engine will not
                # appear mid-walk, and repeating it every frame at 2fps would
                # bury the obstacle alerts that still work.
                if not self._ocr_unavailable_announced:
                    self._ocr_unavailable_announced = True
                    log.error("Read mode unavailable: %s", e)
                    if not registry.silent:
                        self._speak_offloop("Text reading is unavailable.")
                return
            self.last_latency_ms = round((time.monotonic() - t0) * 1000, 1)
            self.detections_done += 1
            vision_health.note_frame_processed(latency_ms=self.last_latency_ms)

            new_phrases: list[str] = []
            for line in lines:
                if line.text not in self._last_read_spoken:
                    self._last_read_spoken.add(line.text)
                    new_phrases.append(line.text)
                    bus = get_bus()
                    bus.publish(OcrReadEvent(text=line.text, confidence=line.confidence),
                                priority=Priority.HIGH)
            if not new_phrases:
                return
            phrase = " ".join(new_phrases)
            if not registry.silent:
                self._speak_offloop(phrase)
        except Exception as e:
            log.error("OCR read failed: %s", e)
        finally:
            self._busy = False

    def _maybe_speak(self, confirmed: list[Obstacle]) -> None:
        """Speak the nearest critical obstacle, per-label cooldown. Plan rule:
        terse and certain — 'Person ahead. 2 meters.' — never hedged."""
        if registry.silent:
            return  # public-space mode: the buzz already fired, stay quiet
        critical = [o for o in confirmed if o.priority == "critical"]
        if not critical:
            return
        o = min(critical, key=lambda x: x.distance_m)
        now = time.monotonic()
        if now - self._last_spoken.get(o.label, 0.0) < SPEAK_COOLDOWN_S:
            return
        self._last_spoken[o.label] = now
        where = {"left": "on your left", "right": "on your right", "straight": "ahead"}[o.direction]
        how_far = "Very close." if o.clipped else f"{max(1, round(o.distance_m))} meters."
        self._speak_offloop(f"{o.label} {where}. {how_far}", o.direction)

    def _speak_offloop(self, phrase: str, direction: str = "straight") -> None:
        """Hand `phrase` to the speech thread. Deliberately not awaited: the
        alert must not hold up the next frame, and submit() is still holding
        _busy while this runs."""
        def _run() -> None:
            import backend.ai_modules.speech.tts_piper as tts_piper
            if direction in ("left", "right"):
                tts_piper.speak_panned(phrase, direction)
            else:
                tts_piper.speak(phrase)

        try:
            fut = _speech_pool.submit(_run)
        except RuntimeError as e:  # pool shut down during process teardown
            log.warning("Obstacle alert TTS not dispatched: %s", e)
            return
        # Nothing awaits the future, so an exception inside would vanish.
        fut.add_done_callback(self._log_speech_failure)

    async def read_once(self) -> str:
        """OCR the current view and speak recognized text — read mode's job.

        Distinct from navigate/scan: reads signs, labels, documents aloud.
        Deduplicates so the same line isn't spoken repeatedly across frames.
        """
        from backend.core.vision.frame_ingest import frame_ingestor
        from backend.core.vision.ocr_reader import OCRUnavailable, ocr_frame, ocr_text

        frame, _meta = frame_ingestor.latest_frame()
        if frame is None:
            return ""
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        try:
            lines = await loop.run_in_executor(None, ocr_frame, frame)
        except OCRUnavailable as e:
            # NOT "No readable text in view" — that is a claim about the
            # scene, and the caller asked precisely because they cannot see
            # the scene to know better.
            log.error("Read mode unavailable: %s", e)
            return "Text reading is unavailable."
        self.last_latency_ms = round((time.monotonic() - t0) * 1000, 1)
        self.detections_done += 1
        vision_health.note_frame_processed(latency_ms=self.last_latency_ms)

        if not lines:
            return "No readable text in view."
        # Speak only lines not spoken yet this session.
        phrases: list[str] = []
        for line in lines:
            if line.text not in self._last_read_spoken:
                phrases.append(line.text)
                self._last_read_spoken.add(line.text)
        if not phrases:
            return ""
        phrase = " ".join(phrases)
        if not registry.silent:
            self._speak_offloop(phrase)
        return phrase

    async def scan_once(self) -> str:
        """Describe the current view once and speak it — scan mode's whole job.

        Distinct from navigate: navigate speaks only what can hurt you, as it
        appears. Scan answers "what is around me" on demand, so it reports
        everything the model saw, not just the rangeable hazards.
        """
        from backend.core.vision.frame_ingest import frame_ingestor
        frame, _meta = frame_ingestor.latest_frame()
        if frame is None:
            return ""
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        seen = await loop.run_in_executor(None, detect, frame, True)
        self.last_latency_ms = round((time.monotonic() - t0) * 1000, 1)
        self.detections_done += 1
        # Scan inference counts too. Without this a scan-only session reports
        # fps_processed: null while genuinely doing work — the exact
        # "looks half-wired" signal vision_health exists to prevent.
        vision_health.note_frame_processed(latency_ms=self.last_latency_ms)
        phrase = describe(seen)
        if not registry.silent:
            self._speak_offloop(phrase)
        return phrase

    @staticmethod
    def _log_speech_failure(fut) -> None:
        exc = fut.exception()
        if exc is not None:
            log.warning("Obstacle alert TTS failed: %s", exc)


detection_runner = DetectionRunner()
