"""Would closing this lose work?

"Close Chrome" is a routine, reversible request and should just happen.
"Close VS Code" can throw away unsaved edits and should ask. The difference is
in the target, not the tool, so it cannot be expressed as a capability tier —
hence `confirm_if` on the registry.

There is no general way to ask Windows "does this app have unsaved work". What
there IS, reliably, is the convention that document editors mark a modified
document in the window title: Notepad writes "*Untitled - Notepad", VS Code
writes "● file.py — folder", most JetBrains and Office apps mark it similarly.
So this uses two signals and is deliberately conservative when neither is
conclusive:

  1. A dirty marker in the live window title  -> confirm.
  2. Otherwise, a known-stateless app         -> close silently.
  3. Anything else                            -> confirm.

Rule 3 is the load-bearing one. An unrecognised app is treated as if it might
hold work, because the cost of a needless prompt is a moment's friction and
the cost of a wrong silent close is the user's afternoon. The allowlist is
what keeps the common cases (browsers, media players, chat) friction-free, and
it is a list of names precisely so that adding one is a deliberate act.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Apps that hold no unsaved document state — closing them loses at most a
# scroll position, and all of them restore their session on reopen.
STATELESS_APPS = frozenset({
    "chrome", "google chrome", "chromium", "firefox", "mozilla firefox",
    "edge", "microsoft edge", "msedge", "brave", "opera", "safari",
    "spotify", "vlc", "windows media player", "groove music", "itunes",
    "whatsapp", "telegram", "discord", "slack", "signal", "teams",
    "calculator", "calc", "clock", "weather", "maps", "photos",
    "task manager", "taskmgr", "control panel", "settings",
    "steam", "epic games launcher", "zoom",
})

# Characters editors put in the title of a modified document. Kept explicit
# rather than "any punctuation" so a file legitimately named "*.py" or a
# bulleted title does not make every close prompt.
DIRTY_MARKERS = ("*", "●", "•", "○")  # * ● • ○


def _norm(name: str) -> str:
    n = (name or "").strip().lower()
    for suffix in (".exe", ".lnk"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip()


def _titles_for(app: str) -> list[str]:
    """Live window titles that look like they belong to `app`. Best-effort:
    if the window list cannot be read we return nothing, and the caller's
    unknown-app rule takes over."""
    try:
        import pygetwindow as gw
        return [w.title for w in gw.getAllWindows() if w.title]
    except Exception as e:
        log.debug("window enumeration failed: %s", e)
        return []


def has_unsaved_work(app: str) -> str | None:
    """Return a short reason to confirm, or None to close silently."""
    name = _norm(app)
    if not name:
        return "no application was named"

    for title in _titles_for(app):
        low = title.lower()
        if name not in low:
            continue
        # The marker has to be at the START of the title or of a segment —
        # "Notes*.txt" mid-title is a filename, "*Untitled - Notepad" is a
        # dirty flag.
        head = title.strip()
        if any(head.startswith(m) for m in DIRTY_MARKERS):
            return f"{app} has unsaved changes"

    if name in STATELESS_APPS:
        return None
    # Unrecognised: it might be an editor, a terminal mid-command, or a form.
    return f"{app} may have unsaved work"


def confirm_close_app(args: dict) -> str | None:
    """registry `confirm_if` hook for close_app."""
    return has_unsaved_work(str(args.get("name") or args.get("app") or ""))


def confirm_close_focused() -> str | None:
    """Same question for close_active_window, which names no target — the app
    has to be looked up from whatever currently has focus."""
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        title = win.title if win else ""
    except Exception as e:
        log.debug("active window lookup failed: %s", e)
        return "the focused window could not be identified"
    if not title:
        return "the focused window could not be identified"
    if any(title.strip().startswith(m) for m in DIRTY_MARKERS):
        return f"{title.strip()} has unsaved changes"
    # Title tail is usually the app name: "file.py - Visual Studio Code".
    low = title.lower()
    if any(app in low for app in STATELESS_APPS):
        return None
    return f"{title.strip()!r} may have unsaved work"
