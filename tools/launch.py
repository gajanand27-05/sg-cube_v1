"""Start SG-CUBE and open the HUD — what the desktop / Start-menu shortcut runs.

    pythonw tools/launch.py         start (if not already running) + open the HUD
    pythonw tools/launch.py stop    stop the running SG-CUBE backend

Interim, until the Phase 4 installer (Inno Setup, tray icon) replaces it.

Run with pythonw.exe: no console window. The backend is started with pythonw
too, detached, so closing the browser does not stop it — "Stop SG-CUBE" does.
Uses your .env exactly as the backend always does (host, port, everything).

Single instance: the backend takes a named mutex and writes a PID file
(backend/daemon/main.claim_single_instance). If one is running — or starting
— this opens the HUD for it instead of starting another.

Errors stay visible without a console: the backend's own early output goes to
logs/launcher_boot.log (a crash before logging starts still leaves a trace),
the backend logs to logs/sg_cube.log, and a failed start shows a message box.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
BOOT_TIMEOUT_S = 180  # first boot loads speech + embedding models


def _port() -> int:
    from backend.server.config import settings
    return int(os.environ.get("SG_CUBE_PORT") or settings.app_port)


def _paths():
    from backend.core import paths
    return paths


def is_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _is_sg_cube_backend(proc) -> bool:
    """argv must BE `<python> -m backend.daemon.main ...` — not merely contain
    the text (a shell or an editor showing it would match a substring test)."""
    try:
        argv = proc.cmdline()
        exe = Path(argv[0]).name.lower() if argv else ""
    except Exception:
        return False
    if exe not in ("python.exe", "pythonw.exe", "python", "pythonw"):
        return False
    # Python stops reading options at the first -c / -m / script, so only that
    # one decides: `python -c "..." -m backend.daemon.main` is not the backend.
    for i, arg in enumerate(argv[1:], 1):
        if arg == "-m":
            return argv[i + 1:i + 2] == ["backend.daemon.main"]
        if arg == "-c" or not arg.startswith("-"):
            return False
    return False


def running_instance() -> dict | None:
    """{pid, port} of the SG-CUBE backend that wrote the PID file — only if
    that exact process (same PID AND start time) is alive and is our backend.
    A stale file (crash, reboot, reused PID) is removed and ignored."""
    import psutil
    from backend.daemon.main import pid_file

    pf = pid_file()
    try:
        info = json.loads(pf.read_text(encoding="utf-8"))
        proc = psutil.Process(int(info["pid"]))
        if abs(proc.create_time() - float(info["create_time"])) < 0.01 and _is_sg_cube_backend(proc):
            return {"pid": proc.pid, "port": int(info["port"])}
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    try:
        pf.unlink()
    except OSError:
        pass
    return None


def start_server(port: int) -> subprocess.Popen:
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0x08)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    exe = PYTHONW if PYTHONW.exists() else Path(sys.executable)
    boot_log = _paths().LOG_DIR / "launcher_boot.log"
    boot_log.parent.mkdir(parents=True, exist_ok=True)
    out = boot_log.open("wb")  # last start only; sg_cube.log keeps the history
    return subprocess.Popen([str(exe), "-m", "backend.daemon.main", "--port", str(port)],
                            cwd=ROOT, creationflags=flags, stdin=subprocess.DEVNULL,
                            stdout=out, stderr=subprocess.STDOUT)


def wait_until_up(port: int, timeout_s: float = BOOT_TIMEOUT_S,
                  proc: subprocess.Popen | None = None) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_up(port):
            return True
        if proc is not None and proc.poll() is not None:
            return False  # it exited: no point waiting out the timeout
        time.sleep(0.5)
    return False


def stop() -> str:
    """Stop SG-CUBE's own backend — the PID-file process, re-verified — and
    nothing else. Returns what happened, for the message."""
    import psutil

    inst = running_instance()
    if inst is None:
        return "SG-CUBE is not running."
    proc = psutil.Process(inst["pid"])
    if not _is_sg_cube_backend(proc):  # re-check right before acting
        return "SG-CUBE is not running."
    # ponytail: TerminateProcess — a hard stop; the lifespan's service shutdown
    # doesn't run (a detached pythonw has no console to send Ctrl+C to). Memory
    # and logs are SQLite/line-flushed, so nothing half-written survives. Upgrade
    # path: a local-only POST /api/shutdown the Phase 4 tray icon calls first.
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()
    try:
        from backend.daemon.main import pid_file
        pid_file().unlink()
    except OSError:
        pass
    return "SG-CUBE stopped."


def _message(text: str, error: bool = False) -> None:
    """pythonw has no console, so tell the user in a dialog."""
    ctypes.windll.user32.MessageBoxW(None, text, "SG-CUBE", 0x10 if error else 0x40)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "stop":
        _message(stop())
        return 0

    inst = running_instance()
    port = inst["port"] if inst else _port()
    proc = None
    if inst is None and not is_up(port):
        proc = start_server(port)
    if not wait_until_up(port, proc=proc):
        logs = _paths().LOG_DIR
        _message("SG-CUBE did not start.\n\nSee:\n"
                 f"{logs / 'sg_cube.log'}\n{logs / 'launcher_boot.log'}", error=True)
        return 1
    webbrowser.open(f"http://127.0.0.1:{port}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
