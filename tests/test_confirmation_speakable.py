"""CAUTION-tool confirmation: speakable on the voice path, and expiring.

Raising the token to 128 bits was right, but it made the token 22 characters
of base64url while the prompt still said "please say 'confirm <token>'" — an
instruction no user can carry out by voice. The strong token stays as the
machine credential; a short single-use code exists for speech.
"""
import asyncio
import time

import pytest

from backend.core.tools import sandbox
from backend.core.tools.registry import REGISTRY, SecurityLevel


def _confirm(guard, key):
    """Run confirm() and report only whether the credential was accepted.

    A rejected key returns an error ToolResult without ever invoking the tool;
    an accepted one actually executes it, and we don't care what a real
    send_email/delete_file does here — only that the gate let it through.
    """
    try:
        return asyncio.run(guard.confirm(key))
    except Exception as e:          # the tool itself blew up => gate passed
        return type("Passed", (), {"reason": None, "tool_error": str(e)})()


@pytest.fixture()
def caution_tool():
    name = next((n for n, t in REGISTRY.items() if t.security == SecurityLevel.CAUTION), None)
    if name is None:
        pytest.skip("no CAUTION tool registered")
    return name


def test_the_prompt_asks_for_something_a_person_can_say(caution_tool):
    """The load-bearing assertion: the spoken instruction must not quote the
    22-char base64 token, or the voice path is impossible to complete."""
    guard = sandbox.PermissionGuard()
    res = guard.check(caution_tool, {})
    token = res.data["token"]

    assert token not in res.message, "the unspeakable token is still quoted at the user"
    code = next(w for w in res.message.replace("'", " ").split() if w.isdigit())
    assert len(code) == 4 and code.isdigit()


def test_confirm_accepts_the_spoken_code(caution_tool):
    guard = sandbox.PermissionGuard()
    res = guard.check(caution_tool, {})
    code = next(w for w in res.message.replace("'", " ").split() if w.isdigit())

    out = _confirm(guard, code)
    assert "Invalid or expired" not in (out.reason or "")


def test_confirm_still_accepts_the_token_so_the_ui_path_is_unchanged(caution_tool):
    guard = sandbox.PermissionGuard()
    token = guard.check(caution_tool, {}).data["token"]
    out = _confirm(guard, token)
    assert "Invalid or expired" not in (out.reason or "")


def test_transcribed_separators_are_tolerated(caution_tool):
    """STT renders spoken digits as '4 8 2 1' or '4-8-2-1' as often as '4821'."""
    guard = sandbox.PermissionGuard()
    res = guard.check(caution_tool, {})
    code = next(w for w in res.message.replace("'", " ").split() if w.isdigit())

    out = _confirm(guard, "-".join(code))
    assert "Invalid or expired" not in (out.reason or "")


def test_a_code_is_single_use(caution_tool):
    """Otherwise one overheard 'confirm 4821' re-arms forever."""
    guard = sandbox.PermissionGuard()
    res = guard.check(caution_tool, {})
    code = next(w for w in res.message.replace("'", " ").split() if w.isdigit())

    _confirm(guard, code)
    again = _confirm(guard, code)
    assert "Invalid or expired" in (again.reason or "")


def test_pending_confirmations_expire(caution_tool, monkeypatch):
    """A pending confirmation is an armed action. A 'yes' an hour later must
    not fire something the user has long forgotten asking about — and before
    this, _pending also grew without bound."""
    guard = sandbox.PermissionGuard()
    res = guard.check(caution_tool, {})
    code = next(w for w in res.message.replace("'", " ").split() if w.isdigit())

    real = time.monotonic
    monkeypatch.setattr(sandbox.time, "monotonic",
                        lambda: real() + sandbox.PENDING_TTL_S + 1)

    out = _confirm(guard, code)
    assert "Invalid or expired" in (out.reason or "")
    assert guard._pending == {} and guard._codes == {}, "expired entries were not purged"


def test_codes_do_not_collide_across_outstanding_confirmations(caution_tool):
    guard = sandbox.PermissionGuard()
    codes = []
    for _ in range(40):
        res = guard.check(caution_tool, {})
        codes.append(next(w for w in res.message.replace("'", " ").split() if w.isdigit()))
    assert len(set(codes)) == len(codes), "two live confirmations shared a spoken code"
