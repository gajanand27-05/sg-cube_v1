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

    endpoint = _LiveEndpoint(volume=30)
    with patch.object(audio, "_endpoint", lambda: endpoint):
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

    endpoint = _LiveEndpoint(muted=False)
    with patch.object(audio, "_endpoint", lambda: endpoint):
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


# ── COM apartment ownership ───────────────────────────────────────────

def test_audio_com_work_is_marshalled_to_the_owning_thread():
    """Every COM touch must happen on the dedicated audio-com thread.

    Two separate live failures came from this not holding. First, tools ran on
    executor threads with no COM apartment at all ("CoInitialize has not been
    called") and every audio tool was dead on every real turn. Then, once
    apartments existed per-thread, the pointers outlived them and a repeated
    real-turn probe hard-crashed with STATUS_ACCESS_VIOLATION — the faulting
    stack pointing at ChromaDB, because the GC that freed the COM pointer
    happened to run there.

    Neither is reachable from a single call on the main thread, which is
    exactly why the suite stayed green through both.
    """
    import threading as _t
    from backend.core.tools import audio

    seen = []
    real_endpoint = audio._endpoint

    def _recording_endpoint():
        seen.append(_t.current_thread().name)
        return real_endpoint()

    result = {}

    def worker():
        with patch.object(audio, "_endpoint", _recording_endpoint):
            result["volume"] = audio._read_volume()

    t = _t.Thread(target=worker, name="pretend-tool-worker")
    t.start()
    t.join(30)

    assert isinstance(result.get("volume"), int), result
    assert seen, "_endpoint was never called"
    assert all(n.startswith("audio-com") for n in seen), (
        f"COM was touched on {seen} — it must only ever run on the dedicated "
        "audio-com thread, whose apartment outlives every pointer it creates"
    )
