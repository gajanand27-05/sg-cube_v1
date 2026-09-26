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
    # open a pre-filled draft; the user presses Send, never this code
    "send_email", "send_whatsapp",
})

# ALLOW tools that still need a yes on follow-up / barge-in turns when phi3 is
# unavailable: those turns are where a misheard phrase slips in, and these two
# write into long-term memory that shapes every later answer.
HUD_ON_LOW_CONFIDENCE = frozenset({"remember", "set_preference"})

HUD_CONFIRM = frozenset({
    "delete_file", "delete_contact", "send_to_phone",
    "shutdown_pc", "restart_pc", "sleep_pc",
    "write_file", "edit_file", "insert_lines", "type_text",
    "browser_click", "browser_type", "close_chrome_tab",
})

# A watcher's action must not register another watcher: that is how a
# one-shot trigger becomes an unbounded chain nobody set up.
_NEVER_FROM_BACKGROUND = frozenset({"monitor_battery", "monitor_folder"})


def policy_fingerprint(name: str) -> str:
    """What a watcher was confirmed against: the tool's schema and policy
    class (tier, trust, guard, which list it is on). If any of it changes, the
    user confirmed something that no longer exists — the watcher must stop."""
    import hashlib
    import json

    tool = REGISTRY.get(name)
    if tool is None:
        return ""
    bucket = "allow" if name in ALLOW else "hud" if name in HUD_CONFIRM else "other"
    blob = json.dumps({
        "schema": tool.schema.get("parameters", {}),
        "tier": getattr(getattr(tool, "tier", None), "value", None),
        "trusted": bool(getattr(tool, "trusted", False)),
        "guarded": callable(getattr(tool, "confirm_if", None)),
        "bucket": bucket,
    }, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


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

    Read-only tools only (decided 2026-09-26). A fired watcher can speak its
    announcement and run a read-only tool — nothing else: no ALLOW tool
    (add_contact, send_email and send_whatsapp are side effects nobody asked
    for at that moment), no HUD tool (nobody there to say yes), and no
    monitor_* (a watcher creating watchers is an unbounded chain).
    """
    tool = REGISTRY.get(name)
    if tool is None:
        return f"{name!r} is not a known tool"
    if name in _NEVER_FROM_BACKGROUND:
        return f"{name} cannot be started by another background action"
    if getattr(tool, "tier", CapabilityTier.DESTRUCTIVE) != CapabilityTier.READONLY:
        return f"{name} changes something, and only read-only tools run in the background"
    return None


def without_verifier(name: str, tier, explicit_trigger: bool, guard_reason: str | None):
    """Decision when the phi3 deep check is unavailable (local Ollama down).

    -> ("allow", None) | ("confirm", None) | ("refuse", reason)
    """
    if name in ALLOW:
        if guard_reason:
            return "confirm", None
        if name in HUD_ON_LOW_CONFIDENCE and not explicit_trigger:
            return "confirm", None
        return "allow", None
    if name in HUD_CONFIRM:
        return "confirm", None
    return "refuse", (f"{name} needs the local safety check, and local Ollama "
                      "is not running")


class Prepared:
    """A call made ready to be confirmed: `args` are what will run (resolved
    and bound), `details` are what the user is shown, `refusal` means there is
    nothing sensible to ask about."""

    def __init__(self, args: dict, details: list[str] | None = None,
                 refusal: str | None = None):
        self.args = args
        self.details = details or []
        self.refusal = refusal


def prepare_confirmation(name: str, args: dict) -> Prepared:
    """Resolve what a confirmation is really about BEFORE asking.

    The approved digest covers the args returned here, so the user approves
    exactly what will run — not a fragment the tool resolves differently later.
    """
    args = dict(args or {})
    if name == "delete_file":
        from backend.core.tools.files import PathRefused, resolve_delete_targets

        try:
            targets = resolve_delete_targets(str(args.get("file", "")))
        except PathRefused as e:
            return Prepared(args, refusal=str(e))
        if not targets:
            return Prepared(args, refusal=f"no file matches {args.get('file')!r}")
        if len(targets) > 1:
            return Prepared(args, refusal=(
                f"{args.get('file')!r} matches {len(targets)} files — say which one: "
                + "; ".join(str(t) for t in targets)))
        from backend.core.tools.files import permanent_delete_reason

        target = targets[0]
        permanent = permanent_delete_reason(target)
        lines = [str(target)]
        if permanent:
            # First line: it becomes the spoken detail and the dialog's top row.
            lines.insert(0, f"PERMANENT DELETE, cannot be undone: {permanent}")
        return Prepared({**args, "file": str(target)}, lines)

    if name == "close_chrome_tab":
        from backend.core import chrome_tabs

        if not chrome_tabs.available():
            return Prepared(args)  # the tool itself reports why it cannot run
        query = str(args.get("name", ""))
        titles = [t.title for t in chrome_tabs.list_tabs() if chrome_tabs.matches(query, t.title)]
        if not titles:
            return Prepared(args, refusal=f"no open Chrome tab matches {query!r}")
        return Prepared({**args, "only_if_titles": titles}, titles)

    return Prepared(args, _describe_args(args))


def _describe_args(args: dict, limit: int = 200) -> list[str]:
    """Every argument, so the dialog never asks "write file?" without saying
    which file or what goes in it."""
    out = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        text = " ".join(str(text).split())
        if len(text) > limit:
            text = text[:limit].rstrip() + f"... ({len(str(value))} chars)"
        out.append(f"{key}: {text}")
    return out
