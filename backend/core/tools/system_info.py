"""System info tools (Phase 11b) — battery, RAM, CPU via psutil."""
import psutil

from backend.core.tools.registry import tool


@tool
def get_battery() -> dict:
    """Return current battery percentage and charging status."""
    b = psutil.sensors_battery()
    if b is None:
        return {"status": "blocked", "reason": "no battery detected (desktop?)"}
    pct = int(round(b.percent))
    plugged = b.power_plugged
    suffix = "and plugged in" if plugged else "on battery"
    return {
        "status": "success",
        "message": f"battery at {pct}% {suffix}",
        "args": {"percent": pct, "plugged_in": plugged},
    }


@tool
def get_system_status() -> dict:
    """Return CPU% (0.5s sample) and RAM% used."""
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    cpu_int = int(round(cpu))
    ram_int = int(round(mem.percent))
    return {
        "status": "success",
        "message": f"CPU {cpu_int}%, RAM {ram_int}% used",
        "args": {"cpu_percent": cpu_int, "ram_percent": ram_int},
    }
