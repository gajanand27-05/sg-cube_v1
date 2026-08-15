import logging
import threading
import time
from typing import Optional

from backend.core.events import get_bus, Priority
from backend.core.vision.capture import capture_screen
from backend.core.vision.change_detect import dhash, distance
from backend.core.vision.vlm import analyze_screenshot_sync
from backend.core.memory.screen_memory import screen_memory
from backend.core.memory.timeline import timeline
from backend.daemon.ui_events import VisionUpdateEvent
from backend.server.config import settings

log = logging.getLogger(__name__)

class VisionLoop:
    """Background service that periodically 'looks' at the screen."""
    
    def __init__(self, interval: float = 300.0): # Default 5 minutes
        self.interval = interval
        self.enabled = True
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Perceptual hash and title of the last frame we actually ANALYSED,
        # not the last one captured. Comparing against the last analysed
        # frame lets slow drift accumulate until it crosses the threshold,
        # instead of a screen creeping arbitrarily far from what we last
        # understood one sub-threshold step at a time.
        self._last_hash = None
        self._last_title: Optional[str] = None

    def start(self):
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="vision-loop", daemon=True)
        self._thread.start()
        log.info(f"Vision loop started (interval: {self.interval}s)")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("Vision loop stopped")

    def _run_loop(self):
        # All-sync by design: a thread-local ProactorEventLoop next to
        # uvicorn's own proactor loop hung nondeterministically on Windows
        # (Py3.12) — the loop ticked silently and never published. No event
        # loop is created in this thread at all.
        while not self._stop_event.is_set():
            if self.enabled:
                try:
                    self._step()
                except Exception as e:
                    log.error(f"Vision loop step failed: {e}")

            # Wait for interval or stop signal
            self._stop_event.wait(self.interval)

    def _step(self):
        """Single 'glance' at the screen."""
        log.info("Vision loop: taking a glance...")

        # 1. Capture
        img_b64, title = capture_screen()
        if not img_b64:
            log.warning("Vision loop: capture returned no image, skipping step")
            return

        # 2. Change detection. This is the only thing standing between an
        # idle machine and a 35s VLM run at ~96% GPU every 300s, so it is
        # perceptual: the byte-hash it replaced skipped 0 of 9 consecutive
        # live captures and could not skip a single changed pixel. See
        # change_detect.py for the measurements.
        current_hash = dhash(img_b64)
        title_changed = title != self._last_title
        if not title_changed and self._last_hash is not None:
            dist = distance(current_hash, self._last_hash)
            if dist <= settings.vision_change_threshold:
                log.debug(
                    f"Vision loop: screen unchanged (dist={dist} <= "
                    f"{settings.vision_change_threshold}), skipping VLM."
                )
                return

        # 3. Analyze (Local VLM)
        observation = analyze_screenshot_sync(img_b64, title)
        if not observation:
            # Graceful fallback: store a basic observation from the window title
            # alone so the timeline still advances and the WS event still fires.
            # The VLM is only needed for detailed analysis — without it we still
            # track which app is active.
            log.debug("VLM unavailable, storing basic observation")
            observation = {"app": title, "summary": f"Active window: {title}", "keywords": [title], "objects": [], "ocr": []}
            
        # 4. Store (Semantic Memory + Timeline)
        self._last_hash = current_hash
        self._last_title = title
        screen_memory.store_observation(observation)
        
        # Record activity in timeline
        app = observation.get("app", "Unknown")
        summary = observation.get("summary", "")
        timeline.record_event(
            content=f"Working in {app}: {summary}",
            source="vision",
            app=app
        )
        
        log.info(f"Vision loop: captured state in {app}")
        try:
            global latest_observation
            latest_observation = {"app": app, "summary": summary, "timestamp": time.time()}
            get_bus().publish(
                VisionUpdateEvent(
                    description=summary,
                    windows=[app],
                    objects=observation.get("objects"),
                    ocr=observation.get("ocr"),
                ),
                priority=Priority.NORMAL,
            )
        except Exception:
            pass

# Global instance
vision_loop = VisionLoop()

# Cached latest observation for GET /vision/latest
latest_observation: dict | None = None
