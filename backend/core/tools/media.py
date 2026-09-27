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


_AUDIO_SESSION_ACTIVE = 1


def _playing() -> list[str]:
    """Apps with an ACTIVE audio session right now, other than SG-CUBE
    itself (Onyx's own voice). This is audio actually coming out, not a
    media session: a paused player has none, so "nothing playing" is
    knowable but "a player is paused" is not. Unknown (API failure) is
    reported as None by the caller's except, never as "nothing"."""
    import os

    from pycaw.pycaw import AudioUtilities

    me = os.getpid()
    names = []
    for s in AudioUtilities.GetAllSessions():
        if s.State == _AUDIO_SESSION_ACTIVE and s.ProcessId and s.ProcessId != me:
            names.append(s.Process.name() if s.Process else f"pid {s.ProcessId}")
    return names


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
    asked = (action or "playpause").strip().lower().replace(" ", "_")
    key = _ALIASES.get(asked, asked)
    if key not in _VK:
        return ToolResult.error(
            f"unknown media action {action!r} — expected play, pause, next, previous or stop"
        )
    if sys.platform != "win32":
        return ToolResult.error("media keys are only wired up on Windows")
    # The media key is a TOGGLE: "pause" sent to something already paused
    # starts it again. So look first, where Windows can tell us.
    try:
        playing = _playing()
    except Exception as e:  # noqa: BLE001
        log.debug("audio sessions unreadable: %s", e)
        playing = None
    if playing is not None:
        if asked in ("pause", "stop") and not playing:
            return ToolResult.blocked("nothing is playing")
        if asked in ("play", "resume") and playing:
            return ToolResult.success(f"already playing ({', '.join(sorted(set(playing)))})")
    try:
        _press(_VK[key])
    except Exception as e:
        log.warning("media_control(%s) failed: %s", key, e)
        return ToolResult.error(f"could not send the media key: {e}")

    # "Sent", not "paused"/"skipped": the key goes to whichever app holds the
    # media session, and nothing reports back what it did.
    spoken = {
        "playpause": {"pause": "Sent pause.", "play": "Sent play.",
                      "resume": "Sent play."}.get(asked, "Sent play/pause."),
        "next": "Sent next track.",
        "previous": "Sent previous track.",
        "stop": "Sent stop.",
    }[key]
    return ToolResult.success(spoken)
