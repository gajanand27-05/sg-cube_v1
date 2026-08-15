"""Transport controls for whatever is currently playing.

"Pause YouTube" had no tool at all. The planner's only options were
browser_click/browser_type — driving the page by clicking coordinates, which
is both fragile and exactly the class of action that should stay behind a
confirmation prompt. Weakening browser_click to make pause work would have
been the wrong trade: a media intent is not a browser intent.

Windows media keys are the right mechanism. They are delivered to whichever
application currently holds the media session, so one tool covers YouTube in
any browser, Spotify, VLC and the rest, without knowing which is playing or
touching the page.
"""
from __future__ import annotations

import logging
import sys

from backend.core.tools.registry import CapabilityTier, ToolResult, tool

log = logging.getLogger(__name__)

# Virtual-key codes. Sent via keybd_event rather than pyautogui because
# pyautogui's key table does not cover the media keys on Windows.
_VK = {
    "playpause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
}

_ALIASES = {
    "play": "playpause", "pause": "playpause", "resume": "playpause",
    "toggle": "playpause", "play_pause": "playpause",
    "skip": "next", "forward": "next", "next_track": "next",
    "back": "previous", "prev": "previous", "previous_track": "previous",
}

_KEYEVENTF_KEYUP = 0x0002


def _press(vk: int) -> None:
    import ctypes
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: transport control, reversible by the opposite command; touches no page content
def media_control(action: str = "playpause") -> ToolResult:
    """Play, pause, or skip whatever is currently playing — YouTube in a
    browser, Spotify, VLC, anything holding the system media session.

    `action` is "play", "pause", "playpause", "next", "previous" or "stop".
    Use this for "pause", "resume", "skip this song", "next track". Do NOT use
    browser_click for media playback: this reaches the player directly and
    works regardless of which window is focused.

    To START something playing from nothing, use `play_youtube` — this tool
    only controls what is already going."""
    key = (action or "playpause").strip().lower().replace(" ", "_")
    key = _ALIASES.get(key, key)
    if key not in _VK:
        return ToolResult.error(
            f"unknown media action {action!r} — expected play, pause, next, previous or stop"
        )
    if sys.platform != "win32":
        return ToolResult.error("media keys are only wired up on Windows")
    try:
        _press(_VK[key])
    except Exception as e:
        log.warning("media_control(%s) failed: %s", key, e)
        return ToolResult.error(f"could not send the media key: {e}")

    spoken = {
        "playpause": "Toggled playback.",
        "next": "Skipped to the next track.",
        "previous": "Went back a track.",
        "stop": "Stopped playback.",
    }[key]
    return ToolResult.success(spoken)
