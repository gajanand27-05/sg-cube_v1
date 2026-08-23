# Tool Post-Condition Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A side-effecting tool may only report success it actually observed; when it cannot observe, it says so, and when the world disagrees it fails.

**Architecture:** A declared `verify=` callable on the `@tool` decorator, run by the framework at the single `runtime.run_tool` result-coercion chokepoint, producing one of three outcomes (`confirmed` / `unconfirmed` / `contradicted`) into `ToolResult.confidence` and `ToolResult.confidence_reason` — two fields that already exist, already reach the planner via `operator.py`'s `res.model_dump()`, and currently carry a constant `100.0` / `[]`.

**Tech Stack:** Python 3.12, pydantic v2 (`ToolResult` is a `BaseModel`), asyncio, pytest. Windows-only tools (`pycaw`/`comtypes`) in the retrofit task.

**Spec:** `docs/superpowers/specs/2026-08-23-tool-verification-design.md`

## Global Constraints

- **Run tests with `.venv/Scripts/python.exe -m pytest` from the repo root.** System Python lacks `cv2`/`torch`; bare `python -m pytest` fails 5 vision tests for an unrelated reason.
- **Outcome vocabulary is `confirmed` / `unconfirmed` / `contradicted`.** Do NOT use "verified" for these. `AgentCompletedEvent.status == "verified"` already means *Guardian approved the plan before execution*, and it is a typed union in both `backend/daemon/ui_events.py:131` and `frontend/src/lib/uiEvents.ts:36` — renaming it is a py↔ts contract change and is out of scope. The decorator kwarg is still named `verify=`; only the outcome words are constrained.
- **`unconfirmed` keeps `status = SUCCESS`.** Only `contradicted` becomes `ERROR`. Flipping unconfirmed to a failure would break 31 existing tools at once and reintroduce invisible fail-closed behaviour.
- **A failing `verify` must never fail the turn.** Raise, hang, or crash ⇒ `unconfirmed`.
- **No `Co-Authored-By` trailer on commits.**
- Baseline before this work: **940 backend tests passing**, `main` at `2524085`.

---

### Task 1: `verify` on the decorator and the `Tool` dataclass

Registration plumbing only — no behaviour change at call time. Splitting it out means Task 2 can be reviewed purely on outcome logic.

**Files:**
- Modify: `backend/core/tools/registry.py` (the `Tool` dataclass ~line 114-143, and the `tool()` decorator ~line 242-338)
- Test: `tests/test_tool_verification.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `Tool.verify: Optional[Callable[[dict, ToolResult], Optional[str]]]` — dataclass field, defaults `None`
  - `tool(security=..., tier=..., trusted=..., confirm_if=..., verify=None)` — new keyword-only-in-practice parameter, passed through to `Tool(verify=...)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_verification.py`:

```python
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


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_verification.py -v`

Expected: FAIL — `TypeError: tool() got an unexpected keyword argument 'verify'`

- [ ] **Step 3: Add the dataclass field**

In `backend/core/tools/registry.py`, add to the `Tool` dataclass immediately after the `confirm_if` field:

```python
    # Post-condition. Called with (args, result) AFTER the tool returns
    # successfully; returns None when the world agrees with the claim, or a
    # short human reason when it disagrees. Raising means "could not check",
    # which is deliberately different from "it failed" — see the outcome
    # vocabulary in runtime.run_tool.
    #
    # Unlike confirm_if, this one MAY raise: confirm_if guards an action that
    # has not happened yet and must fail closed into asking the user, while by
    # the time this runs the action is already done and there is nobody to ask.
    verify: Optional[Callable[[dict, "ToolResult"], Optional[str]]] = None
```

- [ ] **Step 4: Thread it through the decorator**

In the `tool(...)` signature add the parameter:

```python
def tool(
    security: Any = SecurityLevel.SAFE,
    tier: Any = None,
    trusted: bool = False,
    confirm_if: Optional[Callable[[dict], Optional[str]]] = None,
    verify: Optional[Callable[..., Optional[str]]] = None,
) -> Any:
```

and in the `REGISTRY[name] = Tool(...)` construction add the final argument:

```python
            confirm_if=confirm_if,
            verify=verify,
        )
```

Add one line to the decorator docstring's usage list:

```
      @tool(tier=..., verify=_reads_world_back)                 # post-condition checked after it runs
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_verification.py -v`

Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: 942 passed (940 baseline + 2 new)

- [ ] **Step 7: Commit**

```bash
git add backend/core/tools/registry.py tests/test_tool_verification.py
git commit -m "feat(tools): declare a post-condition on the @tool decorator

Plumbing only: Tool.verify is recorded at registration and nothing runs
it yet. The outcome logic lands next, at the runtime chokepoint.

verify MAY raise, unlike confirm_if. confirm_if guards an action that has
not happened and must fail closed into asking the user; by the time
verify runs the action is done and there is nobody to ask, so a failed
check means 'could not observe', not 'it failed'."
```

---

### Task 2: The three outcomes at the `run_tool` chokepoint

The core of the feature.

**Files:**
- Modify: `backend/core/runtime.py` (`run_tool`, the result-coercion block at lines 80-89)
- Test: `tests/test_tool_verification.py` (append)

**Interfaces:**
- Consumes: `Tool.verify` from Task 1
- Produces:
  - `runtime._UNCONFIRMED_CONFIDENCE: float = 60.0` — module constant
  - `runtime._VERIFY_TIMEOUT_S: float = 2.0` — module constant
  - `async runtime._apply_post_condition(name: str, args: dict, res: ToolResult) -> ToolResult` — returns a possibly-modified `ToolResult`; never raises
  - Observable contract: after a non-`READONLY` tool returns `SUCCESS`, its `ToolResult` carries `confidence == 100.0` with a `confidence_reason` when confirmed, `confidence == 60.0` with a reason when unconfirmed, or `status == ToolStatus.ERROR` with `confidence == 0.0` when contradicted

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_verification.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_verification.py -v`

Expected: the 2 Task-1 tests PASS; the 8 new ones FAIL with `ImportError: cannot import name '_UNCONFIRMED_CONFIDENCE'` or assertion failures on `confidence == 100.0`.

- [ ] **Step 3: Add the constants and the post-condition runner**

In `backend/core/runtime.py`, after the `log = logging.getLogger(__name__)` line, add:

```python
# ── Post-condition outcomes (T-tool-claims-unconfirmed) ──────────────
#
# A side-effecting tool reports the outcome it INTENDED, not the one it
# achieved: set_volume returned "volume set to 50%" without ever reading the
# volume back, stamped confidence 100.0 by this very function. Three outcomes
# now exist instead of one.
#
# Vocabulary is confirmed / unconfirmed / contradicted, NOT "verified" —
# AgentCompletedEvent.status already spends that word on Guardian's
# pre-execution plan approval, and it is a typed union on both sides of the
# py/ts boundary. Two meanings for one word across a process boundary is how
# you get a bug nobody can describe.
_UNCONFIRMED_CONFIDENCE = 60.0
_VERIFY_TIMEOUT_S = 2.0


async def _apply_post_condition(name: str, args: dict, res: ToolResult) -> ToolResult:
    """Check a successful side-effecting tool's claim against the world.

    Never raises and never blocks the loop: verify callables are sync in the
    common case (the audio ones make blocking COM calls), so this dispatches
    to the executor the same way run_tool dispatches sync tools.

    A check that raises or hangs yields UNCONFIRMED, never ERROR. "I could not
    look" is not "it failed", and conflating them is its own false claim.
    """
    from backend.core.tools.registry import REGISTRY, CapabilityTier

    if res.status != ToolStatus.SUCCESS:
        return res

    tool_obj = REGISTRY.get(name)
    if tool_obj is None or tool_obj.tier == CapabilityTier.READONLY:
        # READONLY: the tool's result IS the observation. Reading a second time
        # and believing that one instead buys nothing.
        return res

    if tool_obj.verify is None:
        res.confidence = _UNCONFIRMED_CONFIDENCE
        res.confidence_reason = list(res.confidence_reason) + [
            "unconfirmed: no post-condition declared"
        ]
        return res

    try:
        loop = asyncio.get_running_loop()
        disagreement = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: tool_obj.verify(args, res)),
            timeout=_VERIFY_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        res.confidence = _UNCONFIRMED_CONFIDENCE
        res.confidence_reason = list(res.confidence_reason) + [
            f"unconfirmed: post-condition timed out after {_VERIFY_TIMEOUT_S}s"
        ]
        return res
    except Exception as e:
        res.confidence = _UNCONFIRMED_CONFIDENCE
        res.confidence_reason = list(res.confidence_reason) + [
            f"unconfirmed: post-condition could not run: {e}"
        ]
        return res

    if disagreement:
        log.warning("Tool %r claimed success but the world disagrees: %s", name, disagreement)
        return ToolResult(
            status=ToolStatus.ERROR,
            reason=str(disagreement),
            data=res.data,
            confidence=0.0,
            confidence_reason=[f"contradicted: {disagreement}"],
        )

    res.confidence_reason = list(res.confidence_reason) + ["confirmed: read back and agrees"]
    return res
```

- [ ] **Step 4: Call it from `run_tool`**

In `run_tool`, the block currently reads:

```python
            if isinstance(res, dict):
                # Coerce legacy dicts
                res = ToolResult(
                    ...
                )

            task.result = res
            task.status = TaskStatus.COMPLETED if res.status == ToolStatus.SUCCESS else TaskStatus.FAILED
```

Insert the check between the coercion and the assignment, so it runs on both legacy-dict and native-`ToolResult` returns:

```python
            if isinstance(res, dict):
                # Coerce legacy dicts
                res = ToolResult(
                    ...
                )

            # Between coercion and recording: every tool result, whichever
            # shape it arrived in, gets checked against the world here.
            res = await _apply_post_condition(name, args, res)

            task.result = res
            task.status = TaskStatus.COMPLETED if res.status == ToolStatus.SUCCESS else TaskStatus.FAILED
```

Note this placement means a contradicted result also flips `task.status` to `FAILED`, which is correct and feeds the existing `report_tool_quality` call in `finally` without further change.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tool_verification.py -v`

Expected: PASS (10 tests)

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: 950 passed. **If any pre-existing test fails here, do not adjust the new code to make it pass — read it.** A test that breaks because a tool is now `unconfirmed` is reporting a real change in meaning and needs a decision, not a patch.

- [ ] **Step 7: Commit**

```bash
git add backend/core/runtime.py tests/test_tool_verification.py
git commit -m "feat(tools): check a tool's claim against the world before believing it

run_tool stamped confidence 100.0 on every success, including claims no
tool ever checked -- set_volume reported the level it was ASKED for and
never read the volume back.

Three outcomes now: confirmed (read back, agrees), unconfirmed (no
post-condition, or the check could not run), contradicted (read back,
disagrees). Only contradicted becomes ERROR; unconfirmed stays SUCCESS so
the 31 tools without post-conditions keep working and so this does not
become another invisible fail-closed.

A verify that raises or hangs is unconfirmed, never an error: 'I could
not look' is not 'it failed'."
```

---

### Task 3: Retrofit `audio.py` — the proving ground

Four real tools, three of them relative, against a tool module that is provably wrong today.

**Files:**
- Modify: `backend/core/tools/audio.py` (all four side-effecting tools)
- Test: `tests/test_audio_tool_verification.py` (create)

**Interfaces:**
- Consumes: `tool(verify=...)` from Task 1, the outcome contract from Task 2
- Produces: `audio._read_volume() -> int` and `audio._read_muted() -> bool` — the read-back helpers the post-conditions use

- [ ] **Step 1: Write the anchor test**

This is the test the whole feature exists for. Create `tests/test_audio_tool_verification.py`:

```python
"""The anchor: a volume tool that silently does nothing must not claim success.

set_volume called SetMasterVolumeLevelScalar and then reported the level it
was ASKED for -- while GetMasterVolumeLevelScalar sits one function below in
the same file. A Set that no-ops (another process holding the endpoint in
exclusive mode, the default device changing between calls) produced
"volume set to 50%" at confidence 100.0 with nothing changed.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class _DeadEndpoint:
    """An endpoint whose setters silently no-op — the real failure mode."""

    def __init__(self, volume=30, muted=False):
        self._volume = volume
        self._muted = muted

    def GetMasterVolumeLevelScalar(self):
        return self._volume / 100.0

    def SetMasterVolumeLevelScalar(self, _scalar, _ctx):
        pass  # silently does nothing

    def GetMute(self):
        return self._muted

    def SetMute(self, _value, _ctx):
        pass  # silently does nothing


class _LiveEndpoint(_DeadEndpoint):
    """A working endpoint, for the confirmed case."""

    def SetMasterVolumeLevelScalar(self, scalar, _ctx):
        self._volume = int(round(scalar * 100))

    def SetMute(self, value, _ctx):
        self._muted = bool(value)


def _call(tool_name, **args):
    from backend.core.runtime import runtime
    from backend.core.tools.registry import REGISTRY
    return asyncio.run(
        runtime.run_tool(tool_name, REGISTRY[tool_name].func, args, timeout=5.0)
    )


def test_set_volume_on_a_dead_endpoint_does_not_claim_success():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _DeadEndpoint(volume=30)):
        res = _call("set_volume", level=50)

    assert res.status != ToolStatus.SUCCESS, (
        "set_volume reported success while the volume never moved — this is "
        "the exact claim-without-evidence the feature exists to stop"
    )
    assert "30" in (res.reason or ""), res.reason


def test_set_volume_on_a_live_endpoint_is_confirmed():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _LiveEndpoint(volume=30)):
        res = _call("set_volume", level=50)

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == 100.0
    assert "confirmed" in " ".join(res.confidence_reason)


def test_volume_up_checks_the_end_state_it_expected():
    """Relative tools cannot check args alone: volume_up(10) is only
    verifiable against the pre-state the tool read and would otherwise
    throw away."""
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _DeadEndpoint(volume=30)):
        res = _call("volume_up", amount=10)

    assert res.status != ToolStatus.SUCCESS, (
        "volume_up claimed 'raised from 30% to 40%' with nothing raised"
    )


def test_volume_down_checks_the_end_state_it_expected():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _DeadEndpoint(volume=30)):
        res = _call("volume_down", amount=10)

    assert res.status != ToolStatus.SUCCESS


def test_mute_checks_the_end_state_it_expected():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _DeadEndpoint(muted=False)):
        res = _call("mute")

    assert res.status != ToolStatus.SUCCESS, (
        "mute claimed 'muted' while GetMute still reports unmuted"
    )


def test_mute_on_a_live_endpoint_is_confirmed():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _LiveEndpoint(muted=False)):
        res = _call("mute")

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == 100.0


def test_get_volume_is_readonly_and_unaffected():
    from backend.core.tools import audio
    from backend.core.tools.registry import ToolStatus

    with patch.object(audio, "_endpoint", lambda: _DeadEndpoint(volume=30)):
        res = _call("get_volume")

    assert res.status == ToolStatus.SUCCESS
    assert res.confidence == 100.0


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_tool_verification.py -v`

Expected: the three `_LiveEndpoint` / readonly tests PASS (they already hold), and the four dead-endpoint tests FAIL — each asserting `status != SUCCESS` against a result that is `SUCCESS`. That failure is the bug, reproduced.

- [ ] **Step 3: Rewrite `audio.py` with post-conditions**

Replace the body of `backend/core/tools/audio.py` below the `_clamp` helper with:

```python
def _read_volume() -> int:
    """Current master volume, 0-100, read fresh from the endpoint."""
    return int(round(_endpoint().GetMasterVolumeLevelScalar() * 100))


def _read_muted() -> bool:
    return bool(_endpoint().GetMute())


# ── Post-conditions ───────────────────────────────────────────────────
#
# Each returns None when the world agrees, or a short human reason when it
# does not. Relative tools (volume_up/down, mute) cannot be checked from args
# alone -- volume_up(10) is only meaningful against the pre-state the tool
# read -- so those tools record the end-state they expected in result.data and
# the check reads it back from there.


def _volume_matches(expected: int):
    got = _read_volume()
    return None if got == expected else f"volume is {got}%, expected {expected}%"


def _verify_set_volume(args, result):
    return _volume_matches(_clamp(args.get("level")))


def _verify_relative_volume(args, result):
    expected = (result.data or {}).get("expect_level")
    if expected is None:
        raise ValueError("tool recorded no expected level to check against")
    return _volume_matches(int(expected))


def _verify_mute(args, result):
    expected = (result.data or {}).get("expect_muted")
    if expected is None:
        raise ValueError("tool recorded no expected mute state to check against")
    got = _read_muted()
    if got == bool(expected):
        return None
    return f"mute is {'on' if got else 'off'}, expected {'on' if expected else 'off'}"


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_set_volume)  # tier: audio state change, reversible; trusted: everyday volume tweak, no need to prompt
def set_volume(level: int) -> dict:
    """Set system master volume. `level` is 0-100."""
    level = _clamp(level)
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return {"status": "success", "message": f"volume set to {level}%",
            "data": {"expect_level": level}}


@tool(tier=CapabilityTier.READONLY)  # tier: reads current volume, no side effects
def get_volume() -> dict:
    """Return current system master volume (0-100)."""
    percent = _read_volume()
    return {"status": "success", "message": f"volume is {percent}%", "args": {"level": percent}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_relative_volume)  # trusted: same capability as set_volume, which was already trusted; reversible
def volume_up(amount: int = 10) -> dict:
    """Raise system volume by `amount` percentage points (default 10)."""
    ep = _endpoint()
    current = int(round(ep.GetMasterVolumeLevelScalar() * 100))
    new = _clamp(current + amount)
    ep.SetMasterVolumeLevelScalar(new / 100.0, None)
    return {"status": "success", "message": f"volume raised from {current}% to {new}%",
            "data": {"expect_level": new}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_relative_volume)  # trusted: same capability as set_volume, which was already trusted; reversible
def volume_down(amount: int = 10) -> dict:
    """Lower system volume by `amount` percentage points (default 10)."""
    ep = _endpoint()
    current = int(round(ep.GetMasterVolumeLevelScalar() * 100))
    new = _clamp(current - amount)
    ep.SetMasterVolumeLevelScalar(new / 100.0, None)
    return {"status": "success", "message": f"volume lowered from {current}% to {new}%",
            "data": {"expect_level": new}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_mute)  # trusted: toggles mute, reversible by saying it again
def mute() -> dict:
    """Toggle system mute on/off."""
    ep = _endpoint()
    was_muted = bool(ep.GetMute())
    ep.SetMute(0 if was_muted else 1, None)
    return {"status": "success", "message": "unmuted" if was_muted else "muted",
            "data": {"expect_muted": not was_muted}}
```

Note `get_volume` keeps its `"args"` key rather than `"data"` — `run_tool`'s coercion reads `res.get("args") or res.get("data")` into `ToolResult.data`, and other callers may read `data["level"]`. Do not rename it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_tool_verification.py -v`

Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: 957 passed

- [ ] **Step 6: Commit**

```bash
git add backend/core/tools/audio.py tests/test_audio_tool_verification.py
git commit -m "fix(audio): the volume tools reported what they asked for, not what happened

set_volume called SetMasterVolumeLevelScalar and then reported the level
it was ASKED for -- while GetMasterVolumeLevelScalar sits one function
below in the same file. A Set that silently no-ops (another process
holding the endpoint in exclusive mode, the default device changing
between the two calls) produced 'volume set to 50%' at confidence 100.0
with nothing moved. volume_up, volume_down and mute had the same shape:
each read CURRENT state, then reported INTENDED state, never achieved.

All four now declare a post-condition. The three relative ones record the
end-state they expected in result.data, since volume_up(10) cannot be
checked from its args alone.

Anchor test drives them against an endpoint whose setters no-op, which is
the real failure mode and fails against the previous code."
```

---

### Task 4: Downstream — stop speaking unconfirmed results as confirmed

The tools are honest now; the three things that read them still aren't.

**Files:**
- Modify: `backend/core/brain.py` (`summarize_outcome`, ~lines 33-68)
- Modify: `backend/core/agents/commander.py` (`_confirmed_summary`, ~lines 98-118)
- Modify: `backend/core/prompts/registry.py` (planner system prompt)
- Test: `tests/test_unconfirmed_is_spoken_honestly.py` (create)

**Interfaces:**
- Consumes: `ToolResult.confidence` / `.confidence_reason` semantics from Task 2, `runtime._UNCONFIRMED_CONFIDENCE`
- Produces: `brain._hedge(message: str, result: Any) -> str` — returns `message` unchanged when confirmed, or a hedged form when unconfirmed

- [ ] **Step 1: Write the failing test**

Create `tests/test_unconfirmed_is_spoken_honestly.py`:

```python
"""What Onyx SAYS has to carry what the tool actually knew.

A tool can now report 'I did this but could not confirm it'. If the speech
layer flattens that back into a plain claim, the tool-layer honesty buys
nothing -- the user still hears a confident sentence with no evidence behind
it.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.runtime import _UNCONFIRMED_CONFIDENCE


def _record(name, message, confidence, status="success"):
    return {
        "name": name,
        "result": {
            "status": status,
            "message": message,
            "confidence": confidence,
            "confidence_reason": [],
        },
    }


def test_confirmed_result_is_spoken_plainly():
    from backend.core.brain import summarize_outcome
    spoken = summarize_outcome([_record("set_volume", "volume set to 50%", 100.0)])
    assert spoken == "volume set to 50%"


def test_unconfirmed_result_is_hedged():
    from backend.core.brain import summarize_outcome
    spoken = summarize_outcome(
        [_record("open_app", "opened notepad", _UNCONFIRMED_CONFIDENCE)]
    )
    assert spoken != "opened notepad", "unconfirmed result spoken as a plain claim"
    assert "couldn't confirm" in spoken.lower() or "could not confirm" in spoken.lower()
    assert "opened notepad" in spoken, "the hedge should still say what was attempted"


def test_confirmed_summary_hedges_unconfirmed_too():
    """The confirmation path is the costliest place to lie: the user
    explicitly authorised this action and is waiting to hear it happened."""
    from backend.core.agents.commander import _confirmed_summary

    batch = [{
        "name": "close_app",
        "result": {
            "status": "success",
            "message": "closed chrome",
            "confidence": _UNCONFIRMED_CONFIDENCE,
            "confidence_reason": [],
        },
    }]
    spoken = _confirmed_summary(batch, "close chrome")
    assert "couldn't confirm" in spoken.lower() or "could not confirm" in spoken.lower()


def test_confirmed_summary_leaves_confirmed_alone():
    from backend.core.agents.commander import _confirmed_summary

    batch = [{
        "name": "close_app",
        "result": {
            "status": "success",
            "message": "closed chrome",
            "confidence": 100.0,
            "confidence_reason": [],
        },
    }]
    assert _confirmed_summary(batch, "close chrome") == "closed chrome"


def test_planner_prompt_tells_the_model_what_confidence_means():
    """The tool_results handback already carries confidence via
    operator.py's res.model_dump(). If the prompt never explains it, the model
    narrates confidently regardless and iteration 2 launders the uncertainty
    away."""
    from backend.core.prompts.registry import DEFAULT_PROMPTS
    planner = DEFAULT_PROMPTS["planner"]["content"].lower()
    assert "confidence" in planner
    assert "confirm" in planner


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_unconfirmed_is_spoken_honestly.py -v`

Expected: `test_confirmed_result_is_spoken_plainly` and `test_confirmed_summary_leaves_confirmed_alone` PASS; the other three FAIL.

- [ ] **Step 3: Add the hedge helper in `brain.py`**

Add next to `_result_field` in `backend/core/brain.py`:

```python
def _hedge(message: str, result: Any) -> str:
    """Say what was attempted, and admit when it was not confirmed.

    A tool that could not read the world back still did something — claiming
    nothing happened would be its own inaccuracy. What it must not do is use
    the grammar of completion for an outcome nobody observed.
    """
    from backend.core.runtime import _UNCONFIRMED_CONFIDENCE

    confidence = _result_field(result, "confidence")
    if confidence is None or float(confidence) > _UNCONFIRMED_CONFIDENCE:
        return message
    return f"{message} — though I couldn't confirm it"
```

Then in `summarize_outcome`, change the append line from:

```python
        parts.append(message or str(record.get("name", "")).replace("_", " "))
```

to:

```python
        parts.append(_hedge(message or str(record.get("name", "")).replace("_", " "), result))
```

- [ ] **Step 4: Apply the same hedge in `_confirmed_summary`**

In `backend/core/agents/commander.py`, inside `_confirmed_summary`'s success branch, change:

```python
        if status == "success":
            if msg:
                messages.append(str(msg))
```

to:

```python
        if status == "success":
            if msg:
                from backend.core.brain import _hedge
                messages.append(_hedge(str(msg), res))
```

- [ ] **Step 5: Tell the planner what confidence means**

In `backend/core/prompts/registry.py`, append to the end of the `DEFAULT_PROMPTS["planner"]["content"]` string (currently ends with `If no action is needed, return {{"final_response": "..."}}.`):

Note the prompt is a `.format()` template, so any literal brace you add must be doubled. The text below contains none.

```
Every tool result carries a `confidence` and a `confidence_reason`. A result
with reduced confidence means the tool did the thing but could NOT confirm it
happened. Never describe such a result as confirmed, completed or done — say
what was attempted and that it could not be confirmed. A result with
status "error" and a "contradicted" reason means the tool checked and the
world disagreed: report that it did not happen.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_unconfirmed_is_spoken_honestly.py -v`

Expected: PASS (5 tests)

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: 962 passed

- [ ] **Step 8: Commit**

```bash
git add backend/core/brain.py backend/core/agents/commander.py backend/core/prompts/registry.py tests/test_unconfirmed_is_spoken_honestly.py
git commit -m "fix(voice): speak unconfirmed results as unconfirmed

The tools can now say 'I did this but could not confirm it'. All three
consumers flattened that straight back into a plain claim, so the
tool-layer honesty bought nothing at the speaker.

summarize_outcome and _confirmed_summary hedge; the planner prompt now
explains what confidence means, which matters most because operator.py's
res.model_dump() has always carried the field into the tool_results
handback -- it just carried a constant 100.0, so the model had no reason
to read it.

_confirmed_summary is the costliest of the three: the user explicitly
authorised that action and is waiting to hear whether it happened."
```

---

### Task 5: Ticket and handoff

**Files:**
- Modify: `docs/OPEN_TICKETS.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Add the ticket**

Insert into `docs/OPEN_TICKETS.md`, immediately before the `## T-log-cp1252` heading:

```markdown
## T-tool-claims-unconfirmed (opened + FIXED 2026-08-23)

**Observed**: `set_volume` reported the level it was ASKED for and never read the volume back, at `confidence: 100.0`. Same shape in `volume_up`, `volume_down`, `mute`. 31 `"status": "success"` literals across `backend/core/tools/` are all unchecked claims.

**Mechanism**: no post-condition contract existed, and `runtime.run_tool` stamped every success `confidence=100.0` unconditionally. The class had already been fixed pointwise three times — `"Done."` (`c2fdd13`), `close_matching` reporting success while closing nothing (`952b475`), and the OCR placeholder narrated ahead of its data.

**Fix**: `@tool(verify=...)`, run at the `run_tool` coercion chokepoint. Three outcomes — confirmed / unconfirmed / contradicted — landing in `ToolResult.confidence` and `.confidence_reason`. Only contradicted becomes `ERROR`; unconfirmed stays `SUCCESS` so the un-retrofitted tools keep working and this does not become another invisible fail-closed. A `verify` that raises or hangs is unconfirmed, never an error.

Vocabulary is deliberately NOT "verified": `AgentCompletedEvent.status == "verified"` already means Guardian approved the plan pre-execution, and it is a typed union on both sides of the py/ts boundary.

**Verified by reproducing first**: `set_volume(50)` against an endpoint whose setter silently no-ops — the real failure mode — reported success before, does not after.

**Retrofit status**: `audio.py` (4 tools) done. The other modules still return unconfirmed successes; that is honest but weak, and each should be retrofitted with its own evidence.

**Spec**: `docs/superpowers/specs/2026-08-23-tool-verification-design.md`

**Adjacent, not fixed**: `operator.py:60-64` keys result wrappers `"name"` while `commander.py:114` and `:251` read `wrapper.get("tool")`. That lookup always misses — the timeline records "Executed unknown tool: <msg>" for every confirmed action.
```

- [ ] **Step 2: Update the handoff**

In `HANDOFF.md`, under "Still open", append a new item using the next number in that list (items 2-5 exist; item 1 is struck through as fixed, so this becomes item 6):

```markdown
6. **Tool post-conditions are retrofitted for `audio.py` only.** The contract
   is live (`T-tool-claims-unconfirmed`) and every other side-effecting tool
   now returns an *unconfirmed* success — honest, but weak. Retrofit
   module-by-module, each with its own evidence of a real failure mode, the
   way `audio.py` was done. `chrome_tabs` already has its own before/after
   tab-list diff and should be folded into the contract next.
```

- [ ] **Step 3: Commit**

```bash
git add docs/OPEN_TICKETS.md HANDOFF.md
git commit -m "docs: record T-tool-claims-unconfirmed and the retrofit backlog"
```

---

## Live verification before this is called done

Unit tests on a stubbed endpoint prove the contract, not the pipeline — the same distinction that let `chrome_tabs.close_matching` pass 12 unit tests while closing nothing. Do this by hand with the real machine:

1. Set the system volume to a known value (say 30%) using the Windows mixer.
2. Start Onyx and say *"Onyx, set volume to seventy."*
3. Confirm the volume actually moved AND that what Onyx said matches — a plain claim, not a hedge.
4. Then open something that grabs the audio endpoint in exclusive mode (or unplug/switch the default output device mid-command) and repeat. Onyx must NOT say it set the volume.

Record what was said in both cases. If step 4 still produces a confident claim, the chokepoint is not on the path the voice turn actually takes — find out which path it does take before declaring this finished.
