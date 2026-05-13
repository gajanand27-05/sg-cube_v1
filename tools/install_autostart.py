"""Install / uninstall the SG_CUBE daemon as a Windows Task Scheduler entry
that runs at every user logon. Uses pythonw.exe so no console window appears.

Usage:
    python tools/install_autostart.py install
    python tools/install_autostart.py uninstall
    python tools/install_autostart.py status

Optional flags for `install`:
    --device 22       # input device index (default: system default mic)
    --task-name NAME  # override task name (default: SGCubeDaemon)

Notes:
- No admin required (uses /RL LIMITED).
- The task runs as the current user; it stops on logoff.
- Re-running `install` overwrites the existing task.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TASK_NAME = "SGCubeDaemon"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHONW = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
DAEMON_SCRIPT = PROJECT_ROOT / "tools" / "run_daemon.py"


def _ensure_prereqs() -> None:
    if shutil.which("schtasks") is None:
        sys.exit("schtasks.exe not on PATH — this script is Windows-only.")
    if not PYTHONW.exists():
        sys.exit(f"pythonw.exe not found at {PYTHONW} — run pip install in your venv first.")
    if not DAEMON_SCRIPT.exists():
        sys.exit(f"daemon script not found at {DAEMON_SCRIPT}")


def install(task_name: str, device: int | None) -> None:
    _ensure_prereqs()

    extra = f' --device {device}' if device is not None else ''
    action = f'"{PYTHONW}" "{DAEMON_SCRIPT}"{extra}'

    cmd = [
        "schtasks", "/Create", "/F",
        "/TN", task_name,
        "/TR", action,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"\n✓ installed task '{task_name}' — daemon will start at next logon")
    print(f"   action: {action}")
    print(f"   manually trigger:  schtasks /Run /TN {task_name}")
    print(f"   check status:      python tools/install_autostart.py status")


def uninstall(task_name: str) -> None:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        print(f"✓ removed task '{task_name}'")
    else:
        msg = (result.stderr or result.stdout).strip()
        print(f"task '{task_name}' not removed: {msg}")


def status(task_name: str) -> None:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"task '{task_name}' is not installed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "uninstall", "status"])
    ap.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    ap.add_argument("--device", type=int, default=None,
                    help="(install only) input device index for the daemon")
    args = ap.parse_args()

    if args.action == "install":
        install(args.task_name, args.device)
    elif args.action == "uninstall":
        uninstall(args.task_name)
    else:
        status(args.task_name)


if __name__ == "__main__":
    main()
