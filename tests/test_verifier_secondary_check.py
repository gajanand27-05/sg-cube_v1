"""Phase 0.5 — the deep verifier's `_secondary_check` actually runs now.

Before the fix, `verify()` called `_secondary_check` without `await`. The
result was a coroutine object — always truthy — so `not <coroutine>` was
always False and the rejection path was dead code. Every state-changing
call quietly bypassed the deep safety check.

Contract under test:

1. `_secondary_check` is genuinely invoked when the trigger conditions
   are met (SYSTEM_WRITE/DESTRUCTIVE tier, low confidence, multi-step, or
   legacy CAUTION/CRITICAL security level).
2. When it returns True → verification proceeds normally.
3. When it returns False → verification rejects with the "secondary
   verifier" error.
4. It's actually awaited — no "coroutine was never awaited" warnings.
"""
import asyncio
import sys
import warnings
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)


def _register_stub(name: str, tier):
    """Register a minimal tool with the given tier so `verify()` can find it."""
    from backend.core.tools.registry import REGISTRY, tool, ToolResult

    @tool(tier=tier)
    def _stub_impl() -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

    _stub_impl.__name__ = name
    REGISTRY[name] = REGISTRY.pop("_stub_impl")
    REGISTRY[name].name = name
    REGISTRY[name].schema["name"] = name
    return name


def _make_call(name: str, args=None, confidence=1.0) -> dict:
    return {
        "name": name,
        "args": args or {},
        "reasoning": "test fixture",
        "confidence": confidence,
    }


class _SpyCheck:
    """Async spy that records how many times it was awaited and with what args."""
    def __init__(self, return_value: bool):
        self.return_value = return_value
        self.calls: list[tuple] = []

    async def __call__(self, user_query, tool_name, tool_args, reasoning):
        self.calls.append((user_query, tool_name, dict(tool_args), reasoning))
        return self.return_value


def _install_spy(spy):
    """Swap the module-level _secondary_check for our spy. Return restore fn."""
    from backend.core.agent import verifier as v
    original = v._secondary_check
    v._secondary_check = spy  # type: ignore[assignment]
    return lambda: setattr(v, "_secondary_check", original)


def test_secondary_check_is_actually_awaited_and_called():
    """The load-bearing assertion: the spy must have been invoked.

    Prior to the fix, patching _secondary_check made no difference because
    the coroutine it returned was never awaited — the truthiness check
    always passed and no assertion could tell that from a normal pass.
    Requiring the spy to record a call closes that gap.
    """
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase05_stub_calls_check", CapabilityTier.SYSTEM_WRITE)
    spy = _SpyCheck(return_value=True)
    restore = _install_spy(spy)
    try:
        # SYSTEM_WRITE tier triggers deep verification regardless of confidence.
        with warnings.catch_warnings():
            # If the fix regressed and we're back to a bare coroutine call,
            # this warning would fire. Elevate it to an error so the test
            # catches the regression instead of silently passing.
            warnings.filterwarnings("error", message="coroutine .* was never awaited")
            res = _run(verify(user_query="do the thing", call=_make_call(name)))

        assert len(spy.calls) == 1, f"spy called {len(spy.calls)} times, expected 1"
        user_query, tool_name, tool_args, reasoning = spy.calls[0]
        assert user_query == "do the thing"
        assert tool_name == name
        assert reasoning == "test fixture"
        assert res.is_valid is True
        print("  [PASS] _secondary_check was invoked (proved by spy) and awaited")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_secondary_check_pass_lets_verification_proceed():
    """When the deep check returns True → tier gate applies normally."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY
    from backend.server.config import settings

    name = _register_stub("_phase05_stub_pass", CapabilityTier.SYSTEM_WRITE)
    spy = _SpyCheck(return_value=True)
    restore = _install_spy(spy)
    original_flag = settings.auto_confirm_system_write
    settings.auto_confirm_system_write = True  # keep the outcome unambiguous

    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert len(spy.calls) == 1
        assert res.is_valid is True
        # With AUTO_CONFIRM_SYSTEM_WRITE=true, the tier gate passes through
        # after the deep check approves.
        assert res.needs_confirmation is False
        assert res.error == ""
        print("  [PASS] secondary check True → verification proceeds")
    finally:
        REGISTRY.pop(name, None)
        settings.auto_confirm_system_write = original_flag
        restore()


def test_secondary_check_fail_rejects_verification():
    """When the deep check returns False → verify() returns is_valid=False.

    This branch was dead code before the await fix; the whole point of
    Phase 0.5 is that it can now fire.
    """
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase05_stub_fail", CapabilityTier.SYSTEM_WRITE)
    spy = _SpyCheck(return_value=False)
    restore = _install_spy(spy)
    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert len(spy.calls) == 1
        assert res.is_valid is False, "must reject when deep check fails"
        assert "secondary verifier" in (res.error or ""), f"error text should name the layer: {res.error!r}"
        print("  [PASS] secondary check False → verification rejects with clear error")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_readonly_tools_skip_secondary_check():
    """READONLY tier does NOT trigger deep verification — proves the trigger
    conditions are still correct and we didn't over-fire the check."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase05_stub_readonly", CapabilityTier.READONLY)
    spy = _SpyCheck(return_value=False)  # would reject if called
    restore = _install_spy(spy)
    try:
        # High confidence + READONLY + single step + SAFE security → all
        # trigger conditions false → deep check must be skipped.
        res = _run(verify(user_query="test", call=_make_call(name, confidence=0.99)))
        assert len(spy.calls) == 0, "READONLY tools must not trigger the secondary check"
        assert res.is_valid is True
        print("  [PASS] READONLY tools skip the deep check (trigger conditions intact)")
    finally:
        REGISTRY.pop(name, None)
        restore()


if __name__ == "__main__":
    test_secondary_check_is_actually_awaited_and_called()
    test_secondary_check_pass_lets_verification_proceed()
    test_secondary_check_fail_rejects_verification()
    test_readonly_tools_skip_secondary_check()
    print("All Phase 0.5 verifier tests passed.")
