"""Window management + power tools (Phase 11b).

Window mgmt via pygetwindow + pyautogui hotkeys. Power via shutdown.exe / rundll32.
"""
import subprocess

import pyautogui
import pygetwindow as gw

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: minimizes all windows, reversible
def minimize_all() -> ToolResult:
    """Minimize every window and show the desktop (Win+D)."""
    pyautogui.hotkey("win", "d")
    return ToolResult.success("showed desktop")


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: brings window to foreground, reversible
def focus_window(app: str) -> ToolResult:
    """Bring a window to the front by matching its title against `app`.
    Match is case-insensitive substring (e.g. "chrome" matches "Google Chrome").
    """
    needle = app.strip().lower()
    if not needle:
        return ToolResult.blocked("empty app name")

    matches = [w for w in gw.getAllWindows() if w.title and needle in w.title.lower()]
    if not matches:
        return ToolResult.blocked(f"no window matching {app!r}")

    target = matches[0]
    try:
        if target.isMinimized:
            target.restore()
        target.activate()
    except Exception as e:
        return ToolResult.error(str(e))
    return ToolResult.success(f"focused {target.title!r}")


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: closes focused window, reversible by reopening (may lose state)
def close_active_window() -> ToolResult:
    """Close the currently focused window (Alt+F4)."""
    pyautogui.hotkey("alt", "f4")
    return ToolResult.success("closed active window")


@tool(tier=CapabilityTier.READONLY)  # tier: enumerates open windows, no side effects
def list_open_windows() -> ToolResult:
    """List the titles of all open windows."""
    titles = [w.title for w in gw.getAllWindows() if w.title]
    return ToolResult.success(
        message=f"{len(titles)} windows open",
        data={"titles": titles[:30]}
    )


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: locks workstation, reversible by unlock
def lock_screen() -> ToolResult:
    """Lock the workstation (Win+L)."""
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return ToolResult.success("screen locked")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: sleeps machine, disrupts running work
def sleep_pc(seconds: int = 5) -> ToolResult:
    """Put the PC to sleep after a `seconds` countdown (default 5).
    Use cancel_shutdown to abort within the countdown window."""
    seconds = max(0, int(seconds))
    if seconds == 0:
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        )
        return ToolResult.success("sleeping now")
    # shutdown /h is hibernate; for sleep we use timeout + powrprof.
    # shutdown.exe doesn't directly support sleep, so we run a delayed
    # invocation via cmd.
    cmd = (
        f"timeout /t {seconds} && "
        f"rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
    )
    subprocess.Popen(["cmd", "/c", cmd])
    return ToolResult.success(f"sleeping in {seconds}s")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: power state, unsaved work is lost
def shutdown_pc(seconds: int = 10) -> ToolResult:
    """Shut down the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    seconds = max(0, int(seconds))
    subprocess.Popen(["shutdown", "/s", "/t", str(seconds)])
    return ToolResult.success(f"shutting down in {seconds}s — say cancel shutdown to abort")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: power state, unsaved work is lost
def restart_pc(seconds: int = 10) -> ToolResult:
    """Restart the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    seconds = max(0, int(seconds))
    subprocess.Popen(["shutdown", "/r", "/t", str(seconds)])
    return ToolResult.success(f"restarting in {seconds}s — say cancel shutdown to abort")


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: aborts a pending power event, reversible
def cancel_shutdown() -> ToolResult:
    """Cancel a pending shutdown or restart."""
    r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
    if r.returncode != 0 and "no shutdown" in (r.stderr or "").lower():
        return ToolResult.blocked("no shutdown was scheduled")
    return ToolResult.success("shutdown cancelled")
