import time
import threading
import logging
import pyperclip
from backend.core.events import bus, Priority
from backend.daemon.ui_events import ClipboardChangedEvent

log = logging.getLogger(__name__)

class ClipboardWatcher:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.last_text = self._get_clipboard()
        self._stop_event = threading.Event()
        self._thread = None

    def _get_clipboard(self) -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._watch, name="clipboard-watcher", daemon=True)
        self._thread.start()
        log.info("Clipboard watcher started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _watch(self):
        while not self._stop_event.is_set():
            current_text = self._get_clipboard()
            if current_text != self.last_text:
                self.last_text = current_text
                log.debug(f"Clipboard changed: {len(current_text)} chars")
                bus.publish(ClipboardChangedEvent(text=current_text), priority=Priority.LOW)
            time.sleep(self.interval)

# Global instance
watcher = ClipboardWatcher()
