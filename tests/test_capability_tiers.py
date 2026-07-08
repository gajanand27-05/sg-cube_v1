"""Phase 0 Part B + Phase 0.6 — capability tiers, trusted allowlist, Guardian gate.

Contract under test:

- Every tool in REGISTRY has a CapabilityTier attribute.
- A tool declared with bare @tool (no tier arg) defaults to DESTRUCTIVE
  — the fail-closed rule that makes forgotten tiers safe.
- Guardian's verify() lets a READONLY tool through without confirmation.
- Guardian's verify() ALWAYS requires confirmation for DESTRUCTIVE tools.
  No mechanism (including a trusted=True misdeclaration) can bypass this.
- Guardian's verify() blocks untrusted SYSTEM_WRITE and passes trusted
  SYSTEM_WRITE (Phase 0.6 replaces the old global auto_confirm flag).
- Registry-wide trusted-allowlist invariant: exactly the seven declared
  tools carry trusted=True.
"""
import asyncio
import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# The canonical trusted allowlist for SYSTEM_WRITE tools. If you add a
# new trusted tool, add it here too — the invariant test will fail
# otherwise, which is the point.
TRUSTED_ALLOWLIST = {
    "set_volume", "set_brightness", "open_app", "focus_window",
    "remember", "take_note", "set_reminder",
}


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
        assert REGISTRY["_phase0_untagged_sample"].trusted is False
        print("  [PASS] bare @tool defaults to DESTRUCTIVE + untrusted (fail closed)")
    finally:
        REGISTRY.pop("_phase0_untagged_sample", None)


def _register_stub(name: str, tier, trusted: bool = False):
    """Register a minimal tool with the given tier and trust; return the name."""
    from backend.core.tools.registry import REGISTRY, tool, ToolResult

    @tool(tier=tier, trusted=trusted)
    def _stub_impl() -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

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
        "confidence": 1.0,  # high so we skip the low-confidence trigger for deep verification
    }


def _install_secondary_check_stub():
    """The verifier's `_secondary_check` makes a live LLM call. Stub it out.

    Returns a rollback callable.
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


def test_destructive_always_requires_confirmation_even_when_trusted_forced():
    """A DESTRUCTIVE tool declared with trusted=True must:
      - Have its trusted flag reset to False by the decorator (invariant).
      - Still require confirmation at verify() time.
      - Emit a warning in the boot log so the misdeclaration is visible.
    """
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    restore = _install_secondary_check_stub()
    # Capture the boot log so we can assert the warning fires.
    with _capture_registry_warnings() as records:
        name = _register_stub(
            "_phase06_stub_destructive_trusted",
            tier=CapabilityTier.DESTRUCTIVE,
            trusted=True,  # decorator must ignore this
        )
    try:
        # 1. Decorator forced trusted → False.
        assert REGISTRY[name].trusted is False, "decorator must scrub trusted=True on DESTRUCTIVE"
        # 2. Verifier still requires confirmation.
        res = _run(verify(user_query="test", call=_make_call(name)))
        assert res.is_valid is True
        assert res.needs_confirmation is True, "DESTRUCTIVE must require confirmation"
        assert res.is_critical is True
        # 3. Warning fired at registration. The decorator uses
        # f.__name__ at decoration time — for stubs that's the inner
        # function name before our helper renames the registry key, so
        # we assert on content shape rather than the post-rename name.
        matched = [r for r in records
                   if r.levelno == logging.WARNING
                   and "trusted=True" in r.getMessage()
                   and "DESTRUCTIVE" in r.getMessage()]
        assert matched, f"expected a DESTRUCTIVE+trusted warning; got {[r.getMessage() for r in records]}"
        print("  [PASS] DESTRUCTIVE + trusted=True → forced untrusted, still confirms, warning logged")
    finally:
        REGISTRY.pop(name, None)
        restore()


def test_guardian_gates_system_write_on_trusted_flag():
    """SYSTEM_WRITE: untrusted must confirm, trusted must pass through."""
    from backend.core.agent.verifier import verify
    from backend.core.tools.registry import CapabilityTier, REGISTRY

    restore = _install_secondary_check_stub()

    untrusted = _register_stub("_phase06_stub_sw_untrusted", CapabilityTier.SYSTEM_WRITE, trusted=False)
    trusted   = _register_stub("_phase06_stub_sw_trusted",   CapabilityTier.SYSTEM_WRITE, trusted=True)

    try:
        # Untrusted → confirmation required.
        res_untrusted = _run(verify(user_query="test", call=_make_call(untrusted)))
        assert res_untrusted.is_valid is True
        assert res_untrusted.needs_confirmation is True, "untrusted SYSTEM_WRITE must prompt"
        assert res_untrusted.is_critical is False

        # Trusted → passes through, no prompt.
        res_trusted = _run(verify(user_query="test", call=_make_call(trusted)))
        assert res_trusted.is_valid is True
        assert res_trusted.needs_confirmation is False, "trusted SYSTEM_WRITE must skip prompt"
        assert res_trusted.is_critical is False

        print("  [PASS] SYSTEM_WRITE gated by per-tool trusted flag")
    finally:
        REGISTRY.pop(untrusted, None)
        REGISTRY.pop(trusted, None)
        restore()


def test_trusted_allowlist_matches_expected_set():
    """The whole registry snapshot: exactly the allowlist tools carry trusted=True.

    Fails loudly if a new trusted tool sneaks in without updating the
    canonical list at the top of this test file — that's the trip wire
    that makes accidental permission escalation visible in review.
    """
    import backend.core.tools  # noqa: F401
    from backend.core.tools.registry import REGISTRY, CapabilityTier

    actual_trusted = {name for name, t in REGISTRY.items() if t.trusted}
    assert actual_trusted == TRUSTED_ALLOWLIST, (
        f"trusted mismatch — extra: {actual_trusted - TRUSTED_ALLOWLIST}, "
        f"missing: {TRUSTED_ALLOWLIST - actual_trusted}"
    )

    # Every trusted tool must be SYSTEM_WRITE — trust is meaningless on
    # READONLY (never prompts) and forbidden on DESTRUCTIVE (see the
    # decorator guard).
    for name in TRUSTED_ALLOWLIST:
        assert REGISTRY[name].tier == CapabilityTier.SYSTEM_WRITE, (
            f"{name} trusted but tier is {REGISTRY[name].tier.value}"
        )

    # And every non-listed tool must have trusted=False.
    non_listed = {name for name in REGISTRY if name not in TRUSTED_ALLOWLIST}
    for name in non_listed:
        assert REGISTRY[name].trusted is False, f"{name} unexpectedly trusted"

    print(f"  [PASS] exactly {len(TRUSTED_ALLOWLIST)} tools trusted, all SYSTEM_WRITE, rest untrusted")


# ── Helpers ─────────────────────────────────────────────────────────────

class _capture_registry_warnings:
    """Attach a handler to the registry module's logger so we can assert
    on WARNING records emitted during @tool registration."""
    def __enter__(self):
        self._records: list[logging.LogRecord] = []
        self._logger = logging.getLogger("backend.core.tools.registry")
        self._prev_level = self._logger.level
        self._logger.setLevel(logging.DEBUG)

        class _H(logging.Handler):
            def emit(_self, record):
                self._records.append(record)

        self._handler = _H(level=logging.DEBUG)
        self._logger.addHandler(self._handler)
        return self._records

    def __exit__(self, *_):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev_level)


if __name__ == "__main__":
    test_every_tool_has_a_capability_tier()
    test_bare_tool_decorator_defaults_to_destructive()
    test_guardian_passes_readonly_without_confirmation()
    test_destructive_always_requires_confirmation_even_when_trusted_forced()
    test_guardian_gates_system_write_on_trusted_flag()
    test_trusted_allowlist_matches_expected_set()
    print("All capability-tier + trusted-allowlist tests passed.")
