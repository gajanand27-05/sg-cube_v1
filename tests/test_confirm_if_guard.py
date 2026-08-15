"""Trust is sometimes a property of the target, not the tool.

"Close Chrome" is routine and reversible. "Close VS Code" can throw away
unsaved work. Declaring close_app untrusted made the common case prompt every
time; declaring it trusted would silently discard work. Neither is expressible
as a capability tier, because the tier never sees the arguments.

`confirm_if` is the per-call escape hatch. These tests cover the guard's
decisions and — more importantly — that the verifier actually honours it,
since a guard nobody calls is worse than no guard: it reads as protection.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.tools.unsaved_state import (
    DIRTY_MARKERS,
    STATELESS_APPS,
    confirm_close_app,
    has_unsaved_work,
)


def _titles(*titles):
    return patch("backend.core.tools.unsaved_state._titles_for", lambda app: list(titles))


# ── the guard's decisions ──────────────────────────────────────────────

def test_known_stateless_app_closes_silently():
    with _titles("Google Chrome"):
        assert has_unsaved_work("chrome") is None
    with _titles("Spotify Premium"):
        assert has_unsaved_work("spotify") is None


def test_dirty_title_marker_confirms():
    """Editors mark a modified document in the title. That is the one signal
    Windows reliably gives us."""
    with _titles("*Untitled - Notepad"):
        assert has_unsaved_work("notepad") is not None
    with _titles("● main.py - sg_cube - Visual Studio Code"):
        assert has_unsaved_work("visual studio code") is not None


def test_clean_editor_title_still_confirms_because_it_is_unrecognised():
    """Conservative by design: an unknown app might be an editor, a terminal
    mid-command, or a half-filled form. A needless prompt costs a moment; a
    wrong silent close costs the afternoon."""
    with _titles("main.py - sg_cube - Visual Studio Code"):
        assert has_unsaved_work("visual studio code") is not None


def test_a_dirty_marker_mid_title_is_not_a_dirty_flag():
    """A file legitimately named with a star must not make every close
    prompt — the marker only counts at the start."""
    with _titles("notes*.txt - Chrome"):
        assert has_unsaved_work("chrome") is None


def test_a_dirty_chrome_still_confirms():
    """The allowlist is a default, not an override. If the title says
    modified, believe the title."""
    with _titles("*Chrome"):
        assert has_unsaved_work("chrome") is not None


def test_unnamed_app_confirms():
    assert has_unsaved_work("") is not None
    assert confirm_close_app({}) is not None


def test_window_enumeration_failure_falls_back_to_the_name():
    """If the window list can't be read we must not silently close — unknown
    app still confirms, known-stateless still closes."""
    with patch("backend.core.tools.unsaved_state._titles_for", lambda app: []):
        assert has_unsaved_work("chrome") is None
        assert has_unsaved_work("some-editor") is not None


def test_reason_is_human_readable():
    """It gets spoken aloud: "I need your permission to ..."."""
    with _titles("*Untitled - Notepad"):
        reason = has_unsaved_work("notepad")
    assert "notepad" in reason.lower() and len(reason) < 80


# ── the verifier honours it ────────────────────────────────────────────

def _make_call(name, args):
    return {"name": name, "args": args, "confidence": 0.9, "reasoning": "test"}


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _no_llm_check():
    """Patch out the deep LLM check.

    These tests are about the CONFIRMATION decision, which sits after it. With
    Ollama unreachable the fail-closed secondary check rejects first and every
    assertion below would be measuring the wrong gate — and would still "pass"
    for test_a_crashing_guard_fails_closed, for entirely the wrong reason.
    """
    async def _ok(*a, **kw):
        return True
    return patch("backend.core.agent.verifier._secondary_check", _ok)


def test_verifier_confirms_when_the_guard_objects():
    """The load-bearing one. A guard the verifier never calls is worse than no
    guard — it reads as protection while granting silent execution."""
    from backend.core.agent.verifier import verify
    from backend.core.state import manager

    prev = manager._voice_trigger_source
    manager._voice_trigger_source = "wake"
    try:
        with _titles("● main.py - Visual Studio Code"), _no_llm_check():
            res = _run(verify(user_query="close vscode",
                              call=_make_call("close_app", {"name": "visual studio code"})))
    finally:
        manager._voice_trigger_source = prev
    assert res.needs_confirmation, "guard objected but the verifier executed anyway"


def test_verifier_skips_confirmation_when_the_guard_is_satisfied():
    from backend.core.agent.verifier import verify
    from backend.core.state import manager

    prev = manager._voice_trigger_source
    manager._voice_trigger_source = "wake"
    try:
        with _titles("Google Chrome"), _no_llm_check():
            res = _run(verify(user_query="close chrome",
                              call=_make_call("close_app", {"name": "chrome"})))
    finally:
        manager._voice_trigger_source = prev
    assert res.is_valid and not res.needs_confirmation, (
        "closing Chrome should not prompt — that is the whole point of the change"
    )


def test_a_crashing_guard_fails_closed():
    """A broken guard must not hand out the silent execution it exists to
    withhold."""
    from backend.core.agent.verifier import verify
    from backend.core.state import manager
    from backend.core.tools.registry import REGISTRY

    def _boom(args):
        raise RuntimeError("guard is broken")

    tool = REGISTRY["close_app"]
    original = tool.confirm_if
    prev = manager._voice_trigger_source
    manager._voice_trigger_source = "wake"
    try:
        tool.confirm_if = _boom
        with _no_llm_check():
            res = _run(verify(user_query="close chrome",
                              call=_make_call("close_app", {"name": "chrome"})))
    finally:
        tool.confirm_if = original
        manager._voice_trigger_source = prev
    assert res.needs_confirmation, "a crashing guard granted silent execution"


def test_media_control_rejects_an_unknown_action():
    from backend.core.tools.media import media_control
    res = media_control("teleport")
    assert res.status != "success"


def test_media_control_maps_the_words_people_actually_say():
    from backend.core.tools.media import _ALIASES, _VK
    for word in ("play", "pause", "resume", "skip", "next", "previous", "back"):
        key = _ALIASES.get(word, word)
        assert key in _VK, word


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
