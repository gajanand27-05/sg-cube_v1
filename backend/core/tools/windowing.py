"""Window management + power tools (Phase 11b).

Window mgmt via pygetwindow + pyautogui hotkeys. Power via shutdown.exe / rundll32.
"""
import subprocess

import pyautogui
import pygetwindow as gw

from backend.core.tools.registry import tool


@tool
def minimize_all() -> dict:
    """Minimize every window and show the desktop (Win+D)."""
    pyautogui.hotkey("win", "d")
    return {"status": "success", "message": "showed desktop"}


@tool
def focus_window(app: str) -> dict:
    """Bring a window to the front by matching its title against `app`.
    Match is case-insensitive substring (e.g. "chrome" matches "Google Chrome").
    """
    needle = app.strip().lower()
    if not needle:
        return {"status": "blocked", "reason": "empty app name"}

    matches = [w for w in gw.getAllWindows() if w.title and needle in w.title.lower()]
    if not matches:
        return {"status": "blocked", "reason": f"no window matching {app!r}"}

    target = matches[0]
    try:
        if target.isMinimized:
            target.restore()
        target.activate()
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    return {"status": "success", "message": f"focused {target.title!r}"}


@tool
def close_active_window() -> dict:
    """Close the currently focused window (Alt+F4)."""
    pyautogui.hotkey("alt", "f4")
    return {"status": "success", "message": "closed active window"}


@tool
def list_open_windows() -> dict:
    """List the titles of all open windows."""
    titles = [w.title for w in gw.getAllWindows() if w.title]
    return {
        "status": "success",
        "message": f"{len(titles)} windows open",
        "args": {"titles": titles[:30]},
    }


@tool
def lock_screen() -> dict:
    """Lock the workstation (Win+L)."""
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return {"status": "success", "message": "screen locked"}


@tool
def sleep_pc(seconds: int = 5) -> dict:
    """Put the PC to sleep after a `seconds` countdown (default 5).
    Use cancel_shutdown to abort within the countdown window."""
    seconds = max(0, int(seconds))
    if seconds == 0:
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        )
        return {"status": "success", "message": "sleeping now"}
    # shutdown /h is hibernate; for sleep we use timeout + powrprof.
    # shutdown.exe doesn't directly support sleep, so we run a delayed
    # invocation via cmd.
    cmd = (
        f"timeout /t {seconds} && "
        f"rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
    )
    subprocess.Popen(["cmd", "/c", cmd])
    return {"status": "success", "message": f"sleeping in {seconds}s"}


@tool
def shutdown_pc(seconds: int = 10) -> dict:
    """Shut down the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    seconds = max(0, int(seconds))
    subprocess.Popen(["shutdown", "/s", "/t", str(seconds)])
    return {"status": "success", "message": f"shutting down in {seconds}s — say cancel shutdown to abort"}


@tool
def restart_pc(seconds: int = 10) -> dict:
    """Restart the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    seconds = max(0, int(seconds))
    subprocess.Popen(["shutdown", "/r", "/t", str(seconds)])
    return {"status": "success", "message": f"restarting in {seconds}s — say cancel shutdown to abort"}


@tool
def cancel_shutdown() -> dict:
    """Cancel a pending shutdown or restart."""
    r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
    if r.returncode != 0 and "no shutdown" in (r.stderr or "").lower():
        return {"status": "blocked", "reason": "no shutdown was scheduled"}
    return {"status": "success", "message": "shutdown cancelled"}
