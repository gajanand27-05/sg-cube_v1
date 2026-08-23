"""Audio control tools (Phase 11b) — system master volume and mute via pycaw."""
from ctypes import POINTER, cast

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from backend.core.tools.registry import CapabilityTier, tool


def _endpoint():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


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
