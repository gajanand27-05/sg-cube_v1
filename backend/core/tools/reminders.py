"""Reminders + timers (Phase 11c).

Uses threading.Timer for scheduling. On fire, the message is spoken aloud via
Piper. Reminders are in-memory only — daemon restart clears them.

Each reminder has an integer id you can use with cancel_reminder.
"""
import threading
import time
from collections import OrderedDict
from typing import Any

from backend.core.tools.registry import CapabilityTier, tool

_reminders: "OrderedDict[int, dict[str, Any]]" = OrderedDict()
_next_id: int = 1
_lock = threading.Lock()


def _speak_async(text: str) -> None:
    """Speak `text` in a fresh thread so the Timer thread returns quickly
    and the daemon's audio stream isn't held up."""
    def _go():
        try:
            from backend.ai_modules.speech.tts_piper import speak
            speak(text)
        except Exception as e:
            print(f"[reminder] tts failed: {e}")
    threading.Thread(target=_go, daemon=True).start()


def _schedule(delay_seconds: float, message: str, kind: str) -> int:
    global _next_id
    with _lock:
        rid = _next_id
        _next_id += 1

    def fire():
        _speak_async(f"{kind}: {message}" if kind else message)
        with _lock:
            _reminders.pop(rid, None)

    t = threading.Timer(delay_seconds, fire)
    t.daemon = True
    t.start()

    with _lock:
        _reminders[rid] = {
            "timer": t,
            "due_ts": time.time() + delay_seconds,
            "message": message,
            "kind": kind,
        }
    return rid


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: schedules background timer, reversible via cancel
def set_reminder(minutes: int, message: str) -> dict:
    """Schedule a spoken reminder. After `minutes` minutes, SG_CUBE will say
    "Reminder: <message>" aloud. Use for "remind me in 10 minutes to ..."."""
    if minutes <= 0 or not message.strip():
        return {"status": "blocked", "reason": "minutes must be > 0 and message must be non-empty"}
    rid = _schedule(minutes * 60, message.strip(), "Reminder")
    return {
        "status": "success",
        "message": f"reminder set for {minutes} minute(s): {message.strip()}",
        "args": {"id": rid},
    }


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: schedules background timer, reversible via cancel
def set_timer(seconds: int, label: str = "") -> dict:
    """Start a countdown timer. After `seconds` seconds, SG_CUBE will say
    "Timer done" (with the optional label) aloud."""
    if seconds <= 0:
        return {"status": "blocked", "reason": "seconds must be > 0"}
    msg = label.strip() or "timer finished"
    rid = _schedule(float(seconds), msg, "Timer")
    return {
        "status": "success",
        "message": f"timer set for {seconds}s: {msg}",
        "args": {"id": rid},
    }


@tool(tier=CapabilityTier.READONLY)  # tier: lists scheduled entries, no side effects
def list_reminders() -> dict:
    """List active reminders and timers with their remaining time."""
    now = time.time()
    with _lock:
        items = []
        for rid, info in _reminders.items():
            remaining = max(0, int(info["due_ts"] - now))
            items.append(
                {
                    "id": rid,
                    "kind": info["kind"],
                    "message": info["message"],
                    "remaining_seconds": remaining,
                }
            )
    if not items:
        return {"status": "success", "message": "no active reminders", "args": {"reminders": []}}
    summary = ", ".join(f"#{i['id']} in {i['remaining_seconds']}s ({i['message']})" for i in items)
    return {"status": "success", "message": summary, "args": {"reminders": items}}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: cancels scheduled timer, reversible by re-scheduling
def cancel_reminder(id: int) -> dict:
    """Cancel a scheduled reminder or timer by its id (from list_reminders)."""
    with _lock:
        info = _reminders.pop(id, None)
    if info is None:
        return {"status": "blocked", "reason": f"no reminder with id {id}"}
    info["timer"].cancel()
    return {"status": "success", "message": f"cancelled #{id} ({info['message']})"}
