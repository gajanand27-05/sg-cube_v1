"""Phase 0.5 + 0.7 — the deep verifier runs on state-changing tools,
but trusted SYSTEM_WRITE tools skip it for latency.

Phase 0.5 fixed the "coroutine never awaited" no-op so the deep check
would actually reject bad plans. Phase 0.7 keeps that rejection path
alive for untrusted SYSTEM_WRITE and DESTRUCTIVE, but short-circuits it
for READONLY and trusted SYSTEM_WRITE — the Ollama round-trip was
undercutting the whole point of the trusted allowlist ("open chrome"
should feel instant).

Contract under test:

1. `_secondary_check` IS awaited and invoked for untrusted SYSTEM_WRITE.
2. `_secondary_check` IS awaited and invoked for DESTRUCTIVE.
3. `_secondary_check` is NOT invoked for READONLY.
4. `_secondary_check` is NOT invoked for trusted SYSTEM_WRITE.
5. When it returns False on an untrusted call, verify() rejects with the
   expected error text.
6. Cheap local schema validation still runs on trusted tools — a
   missing required arg is rejected BEFORE any short-circuit kicks in.
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


def _register_stub(name: str, tier, trusted: bool = False):
    """Register a minimal (no-arg) tool with the given tier + trust so
    `verify()` can find it."""
    from backend.core.tools.registry import REGISTRY, tool, ToolResult

    @tool(tier=tier, trusted=trusted)
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
    """Swap the module-level _secondary_check for our spy. Returns rollback fn."""
    from backend.core.agent import verifier as v
    original = v._secondary_check
    v._secondary_check = spy  # type: ignore[assignment]
    return lambda: setattr(v, "_secondary_check", original)


# ── Phase 0.5 core: deep check is genuinely awaited on untrusted state changes ──

def test_secondary_check_is_actually_awaited_on_untrusted_system_write():
    """The load-bearing assertion: the spy must have been invoked.

    Prior to Phase 0.5, patching _secondary_check made no difference —
    the coroutine it returned was never awaited, so the check was dead
    code. Elevating "coroutine was never awaited" to an error catches
    any regression to the bare-call pattern.
    """
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase05_stub_untrusted", CapabilityTier.SYSTEM_WRITE, trusted=False)
    spy = _SpyCheck(return_value=True)
    restore = _install_spy(spy)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("error", message="coroutine .* was never awaited")
            res = _run(verify(user_query="do the thing", call=_make_call(name)))

        assert len(spy.calls) == 1, f"spy called {len(spy.calls)} times, expected 1"
        user_query, tool_name, tool_args, reasoning = spy.calls[0]
        assert user_query == "do the thing"
        assert tool_name == name
        assert reasoning == "test fixture"
        assert res.is_valid is True
        # Untrusted SYSTEM_WRITE → confirmation required after deep check passes.
        assert res.needs_confirmation is True
        print("  [PASS] deep check awaited + invoked on untrusted SYSTEM_WRITE")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_secondary_check_fail_rejects_verification():
    """When the deep check returns False → verify() returns is_valid=False.

    This branch was dead code before the await fix; the whole point of
    Phase 0.5 is that it can now fire.
    """
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase05_stub_fail", CapabilityTier.SYSTEM_WRITE, trusted=False)
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


# ── Phase 0.7 fast paths: READONLY and trusted SYSTEM_WRITE skip the deep check ──

def test_readonly_tools_skip_secondary_check():
    """READONLY exits before the LLM call — has no side effect to guard."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase07_stub_readonly", CapabilityTier.READONLY)
    spy = _SpyCheck(return_value=False)  # would reject if called
    restore = _install_spy(spy)
    try:
        res = _run(verify(user_query="test", call=_make_call(name, confidence=0.99)))
        assert len(spy.calls) == 0, "READONLY tools must not trigger the secondary check"
        assert res.is_valid is True
        assert res.needs_confirmation is False
        print("  [PASS] READONLY skips the deep check")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_trusted_system_write_skips_secondary_check():
    """The Phase 0.7 win: a trusted SYSTEM_WRITE tool does NOT incur an
    Ollama round-trip. This is the "open chrome should feel instant"
    contract — trust means both no prompt AND no LLM latency."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase07_stub_sw_trusted", CapabilityTier.SYSTEM_WRITE, trusted=True)
    spy = _SpyCheck(return_value=False)  # would reject if called
    restore = _install_spy(spy)
    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert len(spy.calls) == 0, "trusted SYSTEM_WRITE must not trigger the secondary check"
        assert res.is_valid is True
        assert res.needs_confirmation is False, "trusted → no confirmation prompt either"
        print("  [PASS] trusted SYSTEM_WRITE skips the deep check AND the prompt")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_destructive_still_invokes_secondary_check():
    """DESTRUCTIVE keeps the deep check — the registration guard already
    scrubbed trusted=True on destructive, so this branch is unaffected
    by the Phase 0.7 short-circuit."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase07_stub_destructive", CapabilityTier.DESTRUCTIVE)
    spy = _SpyCheck(return_value=True)
    restore = _install_spy(spy)
    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert len(spy.calls) == 1, f"DESTRUCTIVE must invoke the deep check; got {len(spy.calls)}"
        assert res.is_valid is True
        assert res.needs_confirmation is True
        assert res.is_critical is True
        print("  [PASS] DESTRUCTIVE still invokes the deep check")
    finally:
        REGISTRY.pop(name, None)
        restore()


# ── Guardrail: cheap validation still runs even on trusted tools ────────

def test_cheap_local_validation_runs_on_trusted_tools():
    """A trusted tool with a missing required arg must be rejected by the
    cheap schema check BEFORE the fast-path exit. The point of the
    guardrail: skipping the LLM verifier must not also skip the free
    hallucinated-args guard that already runs on the fast path."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY, tool, ToolResult

    # Register a trusted SYSTEM_WRITE tool with a REQUIRED string arg.
    # If schema validation is bypassed the deep check would be too (both
    # are gated by trust), so the spy count doubles as an "all guards
    # were skipped" alarm.
    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
    def _phase07_stub_needs_arg(target: str) -> ToolResult:  # pragma: no cover
        return ToolResult.success(f"handled {target}")

    name = "_phase07_stub_needs_arg"
    spy = _SpyCheck(return_value=True)
    restore = _install_spy(spy)
    try:
        # Call without the required `target` argument.
        res = _run(verify(user_query="test", call={
            "name": name, "args": {}, "reasoning": "test", "confidence": 1.0,
        }))
        assert res.is_valid is False, "cheap schema check must still reject missing required arg"
        assert "target" in (res.error or ""), f"error should name the missing arg: {res.error!r}"
        assert len(spy.calls) == 0, "deep check must not run when schema check already rejected"
        print("  [PASS] trusted tool with missing arg → rejected by cheap check, deep check skipped")
    finally:
        REGISTRY.pop(name, None)
        restore()


if __name__ == "__main__":
    test_secondary_check_is_actually_awaited_on_untrusted_system_write()
    test_secondary_check_fail_rejects_verification()
    test_readonly_tools_skip_secondary_check()
    test_trusted_system_write_skips_secondary_check()
    test_destructive_still_invokes_secondary_check()
    test_cheap_local_validation_runs_on_trusted_tools()
    print("All Phase 0.5 + 0.7 verifier tests passed.")
