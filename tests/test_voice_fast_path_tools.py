"""Local commands must not depend on the internet.

A live sweep lost 12 consecutive commands to a ~12 second network drop.
Among the casualties: `battery status`, `system status`, `volume up`,
`set brightness to 40`, `list open windows`. Every one of those is a LOCAL
tool that had already been resolved by a rule — they failed only because the
voice path sends everything to a cloud planner.

`_VOICE_FAST_PATH_ACTIONS` covered only {get_time, stop}, and widening it
alone would have changed nothing: those two are the only entries in HANDLERS
that matter here, and `set_volume`/`get_battery` have no handler at all. So
the fast path now also dispatches rule hits straight to the tool REGISTRY.

Going through registry.call (and therefore runtime.run_tool) rather than
calling a handler directly is the load-bearing choice: it keeps the sandbox
guard and, critically, the post-conditions. A fast path that bypassed
run_tool would silently un-do the "never claim what you didn't verify" work
for exactly the tools that have post-conditions.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _turn():
    """A real TurnLatency — production always passes one, and the fast path
    calls turn.seal() unguarded."""
    from backend.core.latency import TurnLatency
    return TurnLatency(request_id="fast-path-test")


def test_every_fast_path_tool_is_safe_to_run_without_the_guardian():
    """The standing guard. The fast path skips the Guardian, so an entry here
    must be one the Guardian would have waved through anyway: READONLY, or
    SYSTEM_WRITE explicitly marked trusted. A DESTRUCTIVE entry would execute
    without the confirmation the tier contract promises can never be silenced.
    """
    import backend.core.tools as _tools  # noqa: F401  (populates REGISTRY)
    from backend.core.tools.registry import REGISTRY, CapabilityTier
    from backend.daemon.trigger import _VOICE_FAST_PATH_TOOLS

    assert _VOICE_FAST_PATH_TOOLS, "no tools on the fast path"
    for action in _VOICE_FAST_PATH_TOOLS:
        tool = REGISTRY.get(action)
        assert tool is not None, f"{action!r} is on the fast path but is not a tool"
        assert tool.tier != CapabilityTier.DESTRUCTIVE, (
            f"{action!r} is DESTRUCTIVE and would skip its confirmation prompt"
        )
        if tool.tier == CapabilityTier.SYSTEM_WRITE:
            assert tool.trusted, (
                f"{action!r} is an untrusted SYSTEM_WRITE tool — the planner "
                "path would prompt for it, so the fast path must not run it"
            )


def test_fast_path_keeps_the_post_condition():
    """set_volume against an endpoint whose setter no-ops must NOT report
    success, even on the fast path. This is the regression that would prove
    the fast path had bypassed runtime.run_tool."""
    from backend.core.tools import audio
    from backend.daemon import trigger

    class _DeadSetter:
        def __init__(self, real):
            self._real = real

        def GetMasterVolumeLevelScalar(self):
            return self._real.GetMasterVolumeLevelScalar()

        def SetMasterVolumeLevelScalar(self, _s, _c):
            pass

    real = audio._endpoint
    spoken = []

    async def _capture(text, device_id=None):
        spoken.append(text)

    async def run():
        with patch.object(audio, "_endpoint", lambda: _DeadSetter(real())), \
             patch.object(trigger, "_speak_selective", _capture), \
             patch.object(trigger, "state_manager"), \
             patch.object(trigger, "get_bus"):
            return await trigger._try_rule_fast_path("set volume to twenty", None, _turn())

    handled = asyncio.run(run())

    assert handled is not None, "the rule fast path did not take this command"
    said = " ".join(spoken).lower()
    assert "volume set to 20" not in said, (
        f"fast path claimed success while the volume never moved: {spoken!r} — "
        "it is bypassing runtime.run_tool and therefore the post-condition"
    )


def test_fast_path_never_reaches_the_planner():
    """The whole point: these must answer with no cloud round trip."""
    from backend.daemon import trigger

    spoken = []

    async def _capture(text, device_id=None):
        spoken.append(text)

    async def _explode(*a, **kw):
        raise AssertionError("fast path called the planner")

    async def run():
        with patch.object(trigger, "_speak_selective", _capture), \
             patch.object(trigger, "state_manager"), \
             patch.object(trigger, "get_bus"), \
             patch.object(trigger.brain, "run_stream", _explode):
            return await trigger._try_rule_fast_path("battery status", None, _turn())

    handled = asyncio.run(run())
    assert handled is not None, "'battery status' did not take the fast path"
    assert spoken, "fast path produced no spoken answer"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
