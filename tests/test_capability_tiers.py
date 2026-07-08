"""Phase 0 Part B — capability tiers + Guardian enforcement.

Contract under test:

- Every tool in REGISTRY has a CapabilityTier attribute.
- A tool declared with bare @tool (no tier arg) defaults to DESTRUCTIVE
  — the fail-closed rule that makes forgotten tiers safe.
- Guardian's verify() lets a READONLY tool through without confirmation.
- Guardian's verify() ALWAYS requires confirmation for DESTRUCTIVE tools,
  even when AUTO_CONFIRM_SYSTEM_WRITE is true.
- Guardian's verify() blocks SYSTEM_WRITE by default and passes it when
  AUTO_CONFIRM_SYSTEM_WRITE is true.
"""
import asyncio
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)


def test_every_tool_has_a_capability_tier():
    """Registry-wide invariant: no tool may have a missing/invalid tier."""
    import backend.core.tools  # triggers auto-discover
    from backend.core.tools.registry import REGISTRY, CapabilityTier

    missing = [name for name, t in REGISTRY.items()
               if not hasattr(t, "tier") or not isinstance(t.tier, CapabilityTier)]
    assert missing == [], f"Tools without a valid tier: {missing}"
    print(f"  [PASS] every one of {len(REGISTRY)} registered tools has a CapabilityTier")


def test_bare_tool_decorator_defaults_to_destructive():
    """A @tool bare (no tier) must fail closed — assume DESTRUCTIVE."""
    import backend.core.tools  # noqa: F401
    from backend.core.tools.registry import REGISTRY, CapabilityTier, tool, ToolResult

    @tool
    def _phase0_untagged_sample() -> ToolResult:
        """Fixture — declared without tier to prove the fail-closed default."""
        return ToolResult.success("ok")

    try:
        assert "_phase0_untagged_sample" in REGISTRY
        assert REGISTRY["_phase0_untagged_sample"].tier == CapabilityTier.DESTRUCTIVE
        print("  [PASS] bare @tool defaults to DESTRUCTIVE (fail closed)")
    finally:
        REGISTRY.pop("_phase0_untagged_sample", None)


def _register_stub(name: str, tier):
    """Register a minimal tool with the given tier and return it for cleanup."""
    from backend.core.tools.registry import REGISTRY, tool, ToolResult

    @tool(tier=tier)
    def _stub_impl() -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

    # Rename in the registry so we don't collide with real tools.
    _stub_impl.__name__ = name
    REGISTRY[name] = REGISTRY.pop("_stub_impl")
    REGISTRY[name].name = name
    REGISTRY[name].schema["name"] = name
    return name


def _make_call(name: str, args=None) -> dict:
    return {
        "name": name,
        "args": args or {},
        "reasoning": "test fixture — direct invocation",
        "confidence": 1.0,  # high so we skip the low-confidence branch of deep verification
    }


def _install_secondary_check_stub():
    """The verifier's `_secondary_check` makes a live LLM call. Stub it out.

    Return callable that restores the original.
    """
    from backend.core.agent import verifier as v
    original = v._secondary_check

    async def _pass(*_a, **_kw):
        return True

    v._secondary_check = _pass  # type: ignore[assignment]
    return lambda: setattr(v, "_secondary_check", original)


def test_guardian_passes_readonly_without_confirmation():
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    name = _register_stub("_phase0_stub_readonly", CapabilityTier.READONLY)
    restore = _install_secondary_check_stub()
    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert res.is_valid is True, res.error
        assert res.needs_confirmation is False
        assert res.is_critical is False
        print("  [PASS] READONLY tool passes without confirmation")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_guardian_always_requires_confirmation_for_destructive():
    """AUTO_CONFIRM_SYSTEM_WRITE=true does NOT silence DESTRUCTIVE tools."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY
    from backend.server.config import settings

    name = _register_stub("_phase0_stub_destructive", CapabilityTier.DESTRUCTIVE)
    restore = _install_secondary_check_stub()
    original_flag = settings.auto_confirm_system_write
    settings.auto_confirm_system_write = True  # try to silence — must not work

    try:
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert res.is_valid is True
        assert res.needs_confirmation is True, "DESTRUCTIVE must require confirmation regardless of flag"
        assert res.is_critical is True
        print("  [PASS] DESTRUCTIVE tool still requires confirmation with AUTO_CONFIRM_SYSTEM_WRITE=true")
    finally:
        REGISTRY.pop(name, None)
        settings.auto_confirm_system_write = original_flag
        restore()


def test_guardian_gates_system_write_on_flag():
    """SYSTEM_WRITE: blocked by default, passes when AUTO_CONFIRM_SYSTEM_WRITE=true."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY
    from backend.server.config import settings

    name = _register_stub("_phase0_stub_system_write", CapabilityTier.SYSTEM_WRITE)
    restore = _install_secondary_check_stub()
    original_flag = settings.auto_confirm_system_write

    try:
        # Default: flag off → confirmation required.
        settings.auto_confirm_system_write = False
        res_off = _run(verify(user_query="test", call=_make_call(name)))
        assert res_off.needs_confirmation is True, "SYSTEM_WRITE must confirm by default"
        assert res_off.is_critical is False

        # Flag on → passes through without confirmation.
        settings.auto_confirm_system_write = True
        res_on = _run(verify(user_query="test", call=_make_call(name)))
        assert res_on.needs_confirmation is False, "SYSTEM_WRITE must auto-approve with flag"
        assert res_on.is_valid is True

        print("  [PASS] SYSTEM_WRITE gated by AUTO_CONFIRM_SYSTEM_WRITE")
    finally:
        REGISTRY.pop(name, None)
        settings.auto_confirm_system_write = original_flag
        restore()


if __name__ == "__main__":
    test_every_tool_has_a_capability_tier()
    test_bare_tool_decorator_defaults_to_destructive()
    test_guardian_passes_readonly_without_confirmation()
    test_guardian_always_requires_confirmation_for_destructive()
    test_guardian_gates_system_write_on_flag()
    print("All capability-tier tests passed.")
