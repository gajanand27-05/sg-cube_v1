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
    # Added 2026-08-15 after "play some music" was found unusable in real use.
    # play_youtube is the same shape as open_app, which is already trusted: it
    # opens a browser tab, reads nothing, writes nothing, and is undone by
    # closing the tab or saying "stop". Prompting for it was not a considered
    # security decision — every comparable everyday action (volume, brightness,
    # launching an app) was already trusted, and its own docstring calls it
    # "the closest thing to JARVIS playing music for you".
    # Residual risk is the same as open_app's and bounded the same way: a
    # misheard transcript can reach it, so it can open an unintended video.
    # Audible, visible, and reversible — which is the bar for this list.
    "play_youtube",
    # Camera control is trusted deliberately: the whole point is hands-free
    # ("connect phone camera"), and a confirmation prompt would defeat it for
    # the blind-assistance user this feature exists for. It is reversible, and
    # it cannot start a camera unseen — the phone must already be paired with
    # the page open and permission granted, and the running stream is visible
    # on both the phone and the HUD.
    # Residual risk, worth knowing: T-wake-word-executes-ambient-audio means a
    # misheard transcript can reach a tool, so this can be started by a
    # mishearing. The preconditions above are what bound that, not the prompt.
    "connect_phone_camera", "disconnect_phone_camera",
    # Same rationale: mode and silence are hands-free controls on an already
    # running camera, and both are trivially reversible by saying the opposite.
    "set_vision_mode", "set_silent_vision",

    # ── 2026-08-15 policy change: trust reversibility, not "writes something"
    #
    # 36 tools prompted, and the split was incoherent rather than considered:
    # `set_volume` was trusted while `volume_up` was not — same capability,
    # same reversibility. `set_brightness` trusted, `brightness_up` not.
    # `render_canvas` asked permission to draw on Onyx's own HUD.
    # `cancel_shutdown` asked permission to CANCEL a destructive event. The
    # list had accreted rather than been designed.
    #
    # The policy is now: routine and reversible runs; meaningful side effects
    # confirm; destructive/outward-facing always confirms. What still prompts
    # after this: write_file, edit_file, insert_lines, type_text,
    # browser_click, browser_type — everything that can overwrite data, inject
    # keystrokes into a focused window, or act on a logged-in page.
    #
    # Worth being honest about the residual risk: this gate is a poor defence
    # against a misheard command anyway (a user prompted constantly approves
    # reflexively), and the real defences are the transcript gate, echo
    # suppression, and the trigger-source rule. Trading a prompt nobody reads
    # for an assistant that works is the intended trade.
    "volume_up", "volume_down", "mute",
    "brightness_up", "brightness_down",
    "open_url", "search_web", "open_folder", "open_notes_today",
    "set_timer", "cancel_reminder", "clipboard_copy",
    "minimize_all", "move_window", "resize_window", "move_resize_window",
    "arrange_windows", "lock_screen", "cancel_shutdown",
    "render_canvas",
    "monitor_battery", "monitor_folder", "set_preference", "update_task_state",
    # Navigation only. browser_click and browser_type stay untrusted: acting
    # on a logged-in page is not reversible, and "confirm purchase" is a click.
    "browser_open", "browser_new_tab", "browser_switch_tab", "browser_close_tab",
    # "Pause YouTube" previously had no tool at all, so the planner's only
    # route to it was browser_click. A media intent is not a browser intent.
    "media_control",
    # Trusted, but with a confirm_if guard: closing Chrome is routine, closing
    # an editor with unsaved work is not. See tools/unsaved_state.py — the
    # guard confirms on a dirty-title marker or an unrecognised app, so the
    # trust only applies to apps known to hold no document state.
    "close_app", "close_active_window",
}

# Trusted tools that still confirm for SOME calls, via registry `confirm_if`.
# Listed separately so the invariant test can assert the guard exists: a
# trusted close_app with no guard silently discards unsaved work.
GUARDED_TRUSTED = {"close_app", "close_active_window"}


def _run(coro):
    # Plain asyncio.run. The old form asked asyncio.get_event_loop() for an
    # ambient loop, which asyncio.run() sets back to None when it finishes — so
    # any earlier test in the session that used asyncio.run made these tests
    # fail with "There is no current event loop", and the suite only passed
    # because collection order happened to put them first. No test here is ever
    # called from inside a running loop, so there is nothing to fall back to.
    return asyncio.run(coro)


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

    # A trusted tool that closes things MUST carry a confirm_if guard. Trust
    # without the guard is what would silently discard unsaved work — the
    # allowlist entry and the guard are one decision, so they are asserted
    # together rather than left to reviewer memory.
    for name in GUARDED_TRUSTED:
        assert callable(getattr(REGISTRY[name], "confirm_if", None)), (
            f"{name} is trusted but has no confirm_if guard — it would close "
            f"an app with unsaved work without asking"
        )

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
