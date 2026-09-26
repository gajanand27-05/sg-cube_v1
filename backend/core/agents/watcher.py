import logging
import threading
import time
from pathlib import Path
import psutil

from backend.core.events import get_bus
from backend.daemon.ui_events import ProactiveEvent, InternalAgentEvent

log = logging.getLogger(__name__)

class WatcherAgent:
    """Autonomous Background Agent.
    Monitors system states (battery, folders) and, when a condition is met,
    fires a ProactiveEvent carrying the FIXED action resolved at setup
    (tools/automation.py) — an announcement and/or one tool call. Nothing a
    watcher stores is ever handed to the planner.
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

    def add_battery_task(self, threshold: int, action: dict):
        self.tasks.append({
            "type": "battery", 
            "threshold": threshold, 
            "action": action, 
            "triggered": False
        })
        get_bus().publish(InternalAgentEvent("Watcher", "registered battery monitor", {"threshold": threshold}))
        log.info(f"Watcher: monitoring battery < {threshold}%")

    def add_folder_task(self, folder: str, pattern: str, action: dict) -> bool:
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
        get_bus().publish(InternalAgentEvent("Watcher", "registered folder monitor", {"folder": str(p)}))
        log.info(f"Watcher: monitoring {p} for {pattern}")
        return True

    def _loop(self):
        while self.running:
            for t in self.tasks:
                if t.get("disabled"):
                    continue
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
                self._fire(t["action"], f"Battery is at {int(b.percent)}%.", task=t)
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
                self._fire(t["action"], f"New file: {files_str}.", task=t)

    def _stale_reason(self, action: dict) -> str | None:
        """Why this watcher's confirmation no longer holds, or None.

        The user confirmed ONE fixed call at setup. If the tool's schema or
        policy class has changed since, or the call is no longer allowed to run
        unattended, or the record predates fixed calls entirely (no
        fingerprint: set up before c98e0ac), that confirmation covers
        something that no longer exists."""
        from backend.core.agent import tool_policy

        name = action.get("tool", "")
        if not name:
            return None  # announce-only: nothing to re-check
        if "fingerprint" not in action:
            return "it was set up before watchers were confirmed"
        if tool_policy.policy_fingerprint(name) != action["fingerprint"]:
            return f"{name} has changed since you confirmed it"
        return tool_policy.background_refusal(name, dict(action.get("args") or {}))

    def _fire(self, action: dict, context: str = "", task: dict | None = None):
        stale = self._stale_reason(action)
        if stale:
            if task is not None:
                task["disabled"] = stale
            log.warning("Watcher disabled: %s", stale)
            get_bus().publish(ProactiveEvent(
                query=(f"I switched off a background watcher because {stale}. "
                       "Set it up again if you still want it.")))
            return
        announce = " ".join(x for x in (action.get("announce", ""), context) if x)
        log.info("Watcher firing: announce=%r tool=%r", announce, action.get("tool"))
        get_bus().publish(ProactiveEvent(query=announce, tool=action.get("tool", ""),
                                         args=dict(action.get("args") or {})))


# Global instance
watcher = WatcherAgent()
