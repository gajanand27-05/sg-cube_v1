import asyncio
import logging
import threading
import time
from typing import Optional

from backend.core.events import bus, Priority
from backend.core.vision.capture import capture_screen
from backend.core.vision.vlm import analyze_screenshot
from backend.core.memory.screen_memory import screen_memory
from backend.core.memory.timeline import timeline
from backend.daemon.ui_events import VisionUpdateEvent

log = logging.getLogger(__name__)

class VisionLoop:
    """Background service that periodically 'looks' at the screen."""
    
    def __init__(self, interval: float = 300.0): # Default 5 minutes
        self.interval = interval
        self.enabled = True
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_img_hash: Optional[str] = None

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
        # Vision tasks are async, but the loop is sync-threaded.
        # We use a dedicated event loop for this thread.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while not self._stop_event.is_set():
            if self.enabled:
                try:
                    loop.run_until_complete(self._step())
                except Exception as e:
                    log.error(f"Vision loop step failed: {e}")
            
            # Wait for interval or stop signal
            self._stop_event.wait(self.interval)
        
        loop.close()

    async def _step(self):
        """Single 'glance' at the screen."""
        log.debug("Vision loop: taking a glance...")
        
        # 1. Capture
        img_b64, title = capture_screen()
        if not img_b64:
            return

        # 2. Simple Change Detection (Efficiency Improvement)
        # Using the length and a slice of the b64 string as a naive hash
        current_hash = f"{len(img_b64)}-{img_b64[:100]}-{img_b64[-100:]}"
        if current_hash == self._last_img_hash:
            log.debug("Vision loop: screen unchanged, skipping VLM.")
            return
            
        # 3. Analyze (Local VLM)
        observation = await analyze_screenshot(img_b64, title)
        if not observation:
            return
            
        # 4. Store (Semantic Memory + Timeline)
        self._last_img_hash = current_hash
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
            bus.publish(VisionUpdateEvent(description=summary, windows=[app]), priority=Priority.NORMAL)
        except Exception:
            pass

# Global instance
vision_loop = VisionLoop()

# Cached latest observation for GET /vision/latest
latest_observation: dict | None = None
