"""Display tools (Phase 11b) — screen brightness via screen-brightness-control."""
import screen_brightness_control as sbc

from backend.core.tools.registry import CapabilityTier, tool


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


def _current() -> int:
    vals = sbc.get_brightness()
    if not vals:
        return 0
    return int(vals[0]) if isinstance(vals, list) else int(vals)


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes display brightness, reversible
def set_brightness(level: int) -> dict:
    """Set screen brightness. `level` is 0-100."""
    level = _clamp(level)
    sbc.set_brightness(level)
    return {"status": "success", "message": f"brightness set to {level}%"}


@tool(tier=CapabilityTier.READONLY)  # tier: reads brightness, no side effects
def get_brightness() -> dict:
    """Return current screen brightness (0-100)."""
    pct = _current()
    return {"status": "success", "message": f"brightness is {pct}%", "args": {"level": pct}}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes brightness state, reversible
def brightness_up(amount: int = 10) -> dict:
    """Raise brightness by `amount` percentage points (default 10)."""
    current = _current()
    new = _clamp(current + amount)
    sbc.set_brightness(new)
    return {"status": "success", "message": f"brightness raised from {current}% to {new}%"}


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: changes brightness state, reversible
def brightness_down(amount: int = 10) -> dict:
    """Lower brightness by `amount` percentage points (default 10)."""
    current = _current()
    new = _clamp(current - amount)
    sbc.set_brightness(new)
    return {"status": "success", "message": f"brightness lowered from {current}% to {new}%"}
