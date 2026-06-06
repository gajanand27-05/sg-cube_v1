import logging
import threading
import time
from pathlib import Path
import psutil

from backend.core.events import bus
from backend.daemon.ui_events import ProactiveEvent, InternalAgentEvent

log = logging.getLogger(__name__)

class WatcherAgent:
    """Autonomous Background Agent.
    Monitors system states (battery, folders) and fires ProactiveEvents
    when conditions are met to wake the Commander Agent.
    """
    
    def __init__(self):
        self.tasks = []
        self.running = False
        self.thread = None

    def start(self):
        if self.thread is not None:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="watcher-agent", daemon=True)
        self.thread.start()
        log.info("Watcher Agent started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        log.info("Watcher Agent stopped.")

    def add_battery_task(self, threshold: int, action: str):
        self.tasks.append({
            "type": "battery", 
            "threshold": threshold, 
            "action": action, 
            "triggered": False
        })
        bus.publish(InternalAgentEvent("Watcher", "registered battery monitor", {"threshold": threshold}))
        log.info(f"Watcher: monitoring battery < {threshold}%")

    def add_folder_task(self, folder: str, pattern: str, action: str) -> bool:
        p = Path(folder).expanduser()
        if not p.exists():
            return False
        
        try:
            known = set(f.name for f in p.glob(pattern) if f.is_file())
        except Exception:
            known = set()
            
        self.tasks.append({
            "type": "folder", 
            "folder": p, 
            "pattern": pattern, 
            "action": action, 
            "known": known
        })
        bus.publish(InternalAgentEvent("Watcher", "registered folder monitor", {"folder": str(p)}))
        log.info(f"Watcher: monitoring {p} for {pattern}")
        return True

    def _loop(self):
        while self.running:
            for t in self.tasks:
                try:
                    self._check_task(t)
                except Exception as e:
                    log.error(f"Watcher task error: {e}")
            time.sleep(5)  # Poll every 5 seconds

    def _check_task(self, t: dict):
        if t["type"] == "battery":
            b = psutil.sensors_battery()
            if not b: return
            if b.percent <= t["threshold"] and not t["triggered"]:
                t["triggered"] = True
                # Fire the planned action
                self._fire(t["action"] + f" (Context: Current battery is {int(b.percent)}%)")
            elif b.percent > t["threshold"]:
                t["triggered"] = False
                
        elif t["type"] == "folder":
            p = t["folder"]
            if not p.exists(): return
            
            current = set(f.name for f in p.glob(t["pattern"]) if f.is_file())
            new_files = current - t["known"]
            
            if new_files:
                t["known"] = current
                files_str = ", ".join(new_files)
                # Fire the planned action
                self._fire(t["action"] + f" (Context: New files detected: {files_str})")

    def _fire(self, query: str):
        log.info(f"Watcher firing proactive event: {query}")
        bus.publish(ProactiveEvent(query=query))


# Global instance
watcher = WatcherAgent()
