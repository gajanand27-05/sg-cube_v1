import os
import psutil

from backend.core.tools.registry import SecurityLevel, ToolResult, tool


@tool
def get_battery() -> ToolResult:
    """Return current battery percentage and charging status."""
    b = psutil.sensors_battery()
    if b is None:
        return ToolResult.blocked("no battery detected (desktop?)")
    pct = int(round(b.percent))
    plugged = b.power_plugged
    suffix = "and plugged in" if plugged else "on battery"
    return ToolResult.success(
        message=f"battery at {pct}% {suffix}",
        data={"percent": pct, "plugged_in": plugged},
    )


@tool
def get_system_status() -> ToolResult:
    """Return CPU% (0.5s sample) and RAM% used."""
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    cpu_int = int(round(cpu))
    ram_int = int(round(mem.percent))
    return ToolResult.success(
        message=f"CPU {cpu_int}%, RAM {ram_int}% used",
        data={"cpu_percent": cpu_int, "ram_percent": ram_int},
    )
