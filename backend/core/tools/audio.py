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


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes machine audio state, reversible
def set_volume(level: int) -> dict:
    """Set system master volume. `level` is 0-100."""
    level = _clamp(level)
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return {"status": "success", "message": f"volume set to {level}%"}


@tool(tier=CapabilityTier.READONLY)  # tier: reads current volume, no side effects
def get_volume() -> dict:
    """Return current system master volume (0-100)."""
    scalar = _endpoint().GetMasterVolumeLevelScalar()
    percent = int(round(scalar * 100))
    return {"status": "success", "message": f"volume is {percent}%", "args": {"level": percent}}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes audio state, reversible
def volume_up(amount: int = 10) -> dict:
    """Raise system volume by `amount` percentage points (default 10)."""
    ep = _endpoint()
    current = int(round(ep.GetMasterVolumeLevelScalar() * 100))
    new = _clamp(current + amount)
    ep.SetMasterVolumeLevelScalar(new / 100.0, None)
    return {"status": "success", "message": f"volume raised from {current}% to {new}%"}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes audio state, reversible
def volume_down(amount: int = 10) -> dict:
    """Lower system volume by `amount` percentage points (default 10)."""
    ep = _endpoint()
    current = int(round(ep.GetMasterVolumeLevelScalar() * 100))
    new = _clamp(current - amount)
    ep.SetMasterVolumeLevelScalar(new / 100.0, None)
    return {"status": "success", "message": f"volume lowered from {current}% to {new}%"}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: toggles mute state, reversible
def mute() -> dict:
    """Toggle system mute on/off."""
    ep = _endpoint()
    current = bool(ep.GetMute())
    ep.SetMute(0 if current else 1, None)
    return {"status": "success", "message": "unmuted" if current else "muted"}
