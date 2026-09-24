"""Which tools may run without a human or a verifier model looking at them.

One reviewable list, shared by every path that has neither: actions fired by
the background watcher, and (next) tool calls when local Ollama — and so the
phi3 deep check — is unavailable. Approved by the user 2026-09-24:

  ALLOW        runs without phi3 and without a prompt
  HUD_CONFIRM  needs an explicit yes (HUD button or voice) first
  anything else that is not READONLY is refused — a tool added later is
               refused until someone decides where it belongs

READONLY tools are not listed: they never needed the deep check.
"""
from __future__ import annotations

from backend.core.tools.registry import REGISTRY, CapabilityTier

ALLOW = frozenset({
    # audio / display / media
    "mute", "set_volume", "volume_up", "volume_down",
    "set_brightness", "brightness_up", "brightness_down", "media_control",
    # opening things
    "open_app", "open_url", "open_folder", "search_web", "play_youtube",
    "browser_open", "browser_new_tab", "browser_switch_tab", "browser_close_tab",
    # windows
    "focus_window", "move_window", "resize_window", "move_resize_window",
    "arrange_windows", "minimize_all", "lock_screen", "cancel_shutdown",
    # closing — each still objects per call through its confirm_if guard
    "close_app", "close_active_window",
    # reminders, notes, memory, canvas
    "set_reminder", "set_timer", "cancel_reminder",
    "take_note", "open_notes_today",
    "remember", "set_preference", "update_task_state",
    "clipboard_copy", "render_canvas",
    # watchers: safe to set up because what they fire is itself gated
    "monitor_battery", "monitor_folder",
    # contacts (reversible with delete_contact)
    "add_contact",
})

HUD_CONFIRM = frozenset({
    "delete_file", "delete_contact", "send_to_phone",
    "shutdown_pc", "restart_pc", "sleep_pc",
    "write_file", "edit_file", "insert_lines", "type_text",
    "browser_click", "browser_type", "close_chrome_tab",
})

# A watcher's action must not register another watcher: that is how a
# one-shot trigger becomes an unbounded chain nobody set up.
_NEVER_FROM_BACKGROUND = frozenset({"monitor_battery", "monitor_folder"})


def schema_problem(name: str, args: dict) -> str | None:
    """Missing required args or wrong primitive types — the verifier's cheap
    checks, shared so a watcher's fixed call is held to the same standard."""
    tool = REGISTRY[name]
    params = tool.schema.get("parameters", {})
    properties = params.get("properties", {})
    for req in params.get("required", []):
        if req not in args:
            return f"Missing required argument {req!r} for tool {name!r}."
    for key, val in args.items():
        expected = (properties.get(key) or {}).get("type")
        ok = {
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "string": lambda v: isinstance(v, str),
            "boolean": lambda v: isinstance(v, bool),
        }.get(expected)
        if ok and not ok(val):
            return f"Argument {key!r} type mismatch."
    return None


def background_refusal(name: str, args: dict) -> str | None:
    """Why this call may NOT run with nobody present, or None if it may.

    Read-only, or on ALLOW; never DESTRUCTIVE whatever the lists say; never
    a HUD_CONFIRM tool (there is no one to say yes); and a guarded tool whose
    guard objects to these arguments is refused rather than asked about.
    """
    tool = REGISTRY.get(name)
    if tool is None:
        return f"{name!r} is not a known tool"
    tier = getattr(tool, "tier", CapabilityTier.DESTRUCTIVE)
    if tier == CapabilityTier.DESTRUCTIVE:
        return f"{name} is destructive and never runs in the background"
    if name in _NEVER_FROM_BACKGROUND:
        return f"{name} cannot be started by another background action"
    if tier != CapabilityTier.READONLY and name not in ALLOW:
        return f"{name} is not on the background allowlist"
    guard = getattr(tool, "confirm_if", None)
    if callable(guard):
        try:
            reason = guard(args)
        except Exception:
            reason = "its safety check could not be evaluated"
        if reason:
            return f"{name} would need confirmation ({reason})"
    return None
