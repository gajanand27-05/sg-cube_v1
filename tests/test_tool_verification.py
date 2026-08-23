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


def _run_custom(payload, tier=None):
    """Run a throwaway tool that returns `payload` verbatim, with no verify."""
    import asyncio as _asyncio
    from backend.core.runtime import runtime
    from backend.core.tools.registry import REGISTRY, CapabilityTier, tool

    @tool(tier=tier or CapabilityTier.SYSTEM_WRITE, trusted=True)
    def _custom_probe_tool() -> dict:
        """Throwaway probe tool with a self-declared confidence."""
        return payload

    try:
        return _asyncio.run(
            runtime.run_tool("_custom_probe_tool", REGISTRY["_custom_probe_tool"].func,
                             {}, timeout=5.0)
        )
    finally:
        REGISTRY.pop("_custom_probe_tool", None)


def test_self_declared_reasoning_survives_the_chokepoint():
    """open_url, render_canvas and arrange_windows already read the world back
    and record WHY. Overwriting their reason with 'no post-condition declared'
    made the result contradict itself, and threw away arrange_windows'
    partial-failure detail — the one number that says some windows did not
    move."""
    res = _run_custom({
        "status": "success",
        "message": "arranged 3 window(s) into grid (2 skipped)",
        "confidence": 65.0,
        "confidence_reason": ["3/5 placements succeeded", "layout=grid on monitor 0"],
    })

    joined = " ".join(res.confidence_reason)
    assert "3/5 placements succeeded" in joined, (
        "the tool's own evidence was erased by the chokepoint"
    )
    assert "said nothing" not in joined
    assert "no post-condition declared" not in joined, (
        "the tool DID record reasoning — saying it declared none contradicts it"
    )
    assert "unconfirmed" in joined.lower()


def test_chokepoint_never_raises_a_tools_own_confidence():
    """A tool that honestly reported LOW confidence must not be talked up to
    60.0 by a branch whose whole point is that nobody checked."""
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE

    res = _run_custom({
        "status": "success",
        "message": "probably did it",
        "confidence": 20.0,
        "confidence_reason": ["the handle went away mid-call"],
    })

    assert res.confidence == 20.0, (
        f"self-declared 20.0 was raised to {res.confidence}"
    )
    assert _UNCONFIRMED_CONFIDENCE > res.confidence


def test_chokepoint_still_caps_an_unchecked_claim():
    """The ceiling is the point: with no post-condition, a tool's own 100.0
    is exactly the unevidenced claim this feature exists to stop."""
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE

    res = _run_custom({
        "status": "success",
        "message": "definitely did it",
        "confidence": 100.0,
        "confidence_reason": [],
    })
    assert res.confidence == _UNCONFIRMED_CONFIDENCE
    assert "no post-condition declared" in " ".join(res.confidence_reason)


def test_audio_post_conditions_survive_a_worker_thread():
    """COM apartments are PER THREAD, and verify runs on _VERIFY_EXECUTOR — a
    different pool from the one the tool body ran on. Before audio._ensure_com
    existed, the REAL endpoint raised

        OSError: [WinError -2147221008] CoInitialize has not been called

    on every worker thread, so the whole audio retrofit was inert while the
    suite stayed green (tests call verify from the main thread, where
    `import comtypes` already put COM up).

    Run out-of-process on purpose: COM interface pointers created on a pool
    thread and released later by the main thread's cyclic GC crash the
    interpreter with an access violation, which would take the whole pytest
    session down. A subprocess contains that.
    """
    import subprocess
    import sys as _sys

    import pytest

    pytest.importorskip("pycaw")
    from backend.core.tools import audio

    try:
        audio._read_volume()
    except Exception as e:  # no audio endpoint on this box (CI)
        pytest.skip(f"no usable audio endpoint: {e}")

    script = (
        "import sys, concurrent.futures\n"
        f"sys.path.insert(0, {str(_project_root)!r})\n"
        "from backend.core.tools import audio\n"
        "pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix='tool-verify')\n"
        "print(pool.submit(audio._read_volume).result(timeout=10))\n"
        "sys.stdout.flush()\n"
        "import os; os._exit(0)\n"
    )
    proc = subprocess.run(
        [_sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, (
        "reading the audio endpoint from a worker thread failed — "
        f"post-conditions run on exactly such a thread:\n{proc.stderr}"
    )
    assert "CoInitialize has not been called" not in proc.stderr
    assert proc.stdout.strip().isdigit(), proc.stdout + proc.stderr


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
