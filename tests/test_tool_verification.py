"""Tool post-condition verification.

A side-effecting tool may only report success it observed. See
docs/superpowers/specs/2026-08-23-tool-verification-design.md.

Vocabulary note: the outcomes are confirmed / unconfirmed / contradicted.
"verified" is NOT used — AgentCompletedEvent.status already spends that word
on Guardian's pre-execution plan approval, on both sides of the py/ts boundary.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_tool_records_a_declared_verify():
    from backend.core.tools.registry import (
        REGISTRY, CapabilityTier, tool,
    )

    def _check(args, result):
        return None

    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_check)
    def _fake_verified_tool(level: int) -> dict:
        """Fake tool for the registration test."""
        return {"status": "success", "message": "ok"}

    try:
        assert REGISTRY["_fake_verified_tool"].verify is _check
    finally:
        REGISTRY.pop("_fake_verified_tool", None)


def test_tool_without_verify_declares_none():
    """A tool that declares no post-condition is not an error — it is
    unconfirmed, which is a different thing and is decided at call time."""
    from backend.core.tools.registry import REGISTRY, CapabilityTier, tool

    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
    def _fake_unverified_tool() -> dict:
        """Fake tool for the registration test."""
        return {"status": "success", "message": "ok"}

    try:
        assert REGISTRY["_fake_unverified_tool"].verify is None
    finally:
        REGISTRY.pop("_fake_unverified_tool", None)


# ── Outcomes at the runtime chokepoint ────────────────────────────────

import asyncio
from contextlib import contextmanager


@contextmanager
def _registered(verify, tier=None, status="success"):
    """Register a throwaway tool with the given post-condition, and clean up.

    Returns the tool's name. The tool itself does nothing — the point is what
    the framework does around it.
    """
    from backend.core.tools.registry import REGISTRY, CapabilityTier, tool

    tier = tier or CapabilityTier.SYSTEM_WRITE

    @tool(tier=tier, trusted=True, verify=verify)
    def _probe_tool(level: int = 1) -> dict:
        """Throwaway probe tool."""
        return {"status": status, "message": "claimed"}

    try:
        yield "_probe_tool"
    finally:
        REGISTRY.pop("_probe_tool", None)


def _run(name, **args):
    from backend.core.runtime import runtime
    from backend.core.tools.registry import REGISTRY
    tool_obj = REGISTRY[name]
    return asyncio.run(
        runtime.run_tool(name, tool_obj.func, args, timeout=5.0)
    )


def test_confirmed_keeps_full_confidence():
    from backend.core.tools.registry import ToolStatus

    with _registered(verify=lambda args, result: None) as name:
        res = _run(name, level=50)

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == 100.0
    assert res.confidence_reason, "a confirmed result should say it was checked"


def test_contradicted_is_not_success():
    """The load-bearing case. The world was read and disagrees; that is a
    failure that happens to have been detected, not a weak success."""
    from backend.core.tools.registry import ToolStatus

    with _registered(verify=lambda args, result: "volume is 30%, expected 50%") as name:
        res = _run(name, level=50)

    assert res.status == ToolStatus.ERROR, (
        f"contradicted result reported {res.status} — this is exactly the "
        "claim-without-evidence the whole change exists to stop"
    )
    assert res.confidence == 0.0
    assert "expected 50%" in " ".join(res.confidence_reason)


def test_undeclared_post_condition_is_unconfirmed_not_failure():
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE
    from backend.core.tools.registry import ToolStatus

    with _registered(verify=None) as name:
        res = _run(name, level=50)

    assert res.status == ToolStatus.SUCCESS, (
        "an undeclared post-condition must not break the 31 tools that have "
        "none yet"
    )
    assert res.confidence == _UNCONFIRMED_CONFIDENCE
    assert "no post-condition" in " ".join(res.confidence_reason).lower()


def test_a_raising_verify_is_unconfirmed_not_error():
    """'I could not look' is not 'it failed'. Turning one into the other is
    its own false claim."""
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE
    from backend.core.tools.registry import ToolStatus

    def _explodes(args, result):
        raise OSError("audio endpoint went away")

    with _registered(verify=_explodes) as name:
        res = _run(name, level=50)

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == _UNCONFIRMED_CONFIDENCE
    assert "audio endpoint went away" in " ".join(res.confidence_reason)


def test_a_hanging_verify_does_not_hang_the_turn():
    import time
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE, _VERIFY_TIMEOUT_S
    from backend.core.tools.registry import ToolStatus

    def _hangs(args, result):
        time.sleep(_VERIFY_TIMEOUT_S + 3)
        return None

    t0 = time.perf_counter()
    with _registered(verify=_hangs) as name:
        res = _run(name, level=50)
    elapsed = time.perf_counter() - t0

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == _UNCONFIRMED_CONFIDENCE
    assert elapsed < _VERIFY_TIMEOUT_S + 2, (
        f"a hanging post-condition held the turn for {elapsed:.1f}s"
    )


def test_readonly_tools_are_not_checked():
    """A read tool's result IS the observation. Checking it would mean reading
    twice and believing the second read for no reason."""
    from backend.core.tools.registry import CapabilityTier, ToolStatus

    called = []

    def _should_not_run(args, result):
        called.append(1)
        return "disagrees"

    with _registered(verify=_should_not_run, tier=CapabilityTier.READONLY) as name:
        res = _run(name, level=50)

    assert not called, "a READONLY tool had its post-condition run"
    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == 100.0


def test_non_success_results_are_not_checked():
    called = []

    def _should_not_run(args, result):
        called.append(1)
        return "disagrees"

    with _registered(verify=_should_not_run, status="blocked") as name:
        res = _run(name, level=50)

    assert not called, "a blocked result had its post-condition run"


def test_verify_receives_the_args_and_the_result():
    """Relative tools (volume_up, mute) need both: args for what was asked,
    result.data for the end-state the tool expected to reach."""
    seen = {}

    def _capture(args, result):
        seen["args"] = args
        seen["message"] = result.message
        return None

    with _registered(verify=_capture) as name:
        _run(name, level=42)

    assert seen["args"] == {"level": 42}
    assert seen["message"] == "claimed"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
