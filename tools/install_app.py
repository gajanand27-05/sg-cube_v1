"""Install SG-CUBE on this laptop: Start-menu and Desktop shortcuts.

    .venv\\Scripts\\python.exe tools/install_app.py install
    .venv\\Scripts\\python.exe tools/install_app.py uninstall

Creates "SG-CUBE" (start + open the HUD) and "Stop SG-CUBE", both running
tools/launch.py with pythonw.exe (no console window). No admin rights needed.
Uninstall removes only these shortcuts and the generated icon — never the
code, the venv or your data. Start-at-logon is separate:
tools/install_autostart.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
LAUNCHER = ROOT / "tools" / "launch.py"
LOGO = ROOT / "frontend" / "public" / "sg-cube-logo.png"


def _icon() -> Path:
    from backend.core import paths

    ico = paths.DATA_DIR / "sg-cube.ico"
    if not ico.exists():
        from PIL import Image

        ico.parent.mkdir(parents=True, exist_ok=True)
        Image.open(LOGO).convert("RGBA").save(ico, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    return ico


def shortcut_paths() -> dict[str, Path]:
    from win32com.shell import shell, shellcon

    start = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)) / "SG-CUBE"
    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
    return {
        "start_app": start / "SG-CUBE.lnk",
        "start_stop": start / "Stop SG-CUBE.lnk",
        "desktop_app": desktop / "SG-CUBE.lnk",
    }


def install() -> list[Path]:
    import win32com.client

    if not PYTHONW.exists():
        sys.exit(f"{PYTHONW} not found — run `uv sync` in {ROOT} first.")
    shell = win32com.client.Dispatch("WScript.Shell")
    icon = _icon()
    made = []
    for key, lnk in shortcut_paths().items():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        sc = shell.CreateShortcut(str(lnk))
        sc.TargetPath = str(PYTHONW)
        sc.Arguments = f'"{LAUNCHER}"' + (" stop" if key == "start_stop" else "")
        sc.WorkingDirectory = str(ROOT)
        sc.IconLocation = str(icon)
        sc.Description = "Stop the SG-CUBE assistant" if key == "start_stop" else "Start SG-CUBE and open the HUD"
        sc.Save()
        made.append(lnk)
    return made


def uninstall() -> list[Path]:
    from backend.core import paths

    gone = []
    for lnk in shortcut_paths().values():
        if lnk.exists():
            lnk.unlink()
            gone.append(lnk)
    folder = shortcut_paths()["start_app"].parent
    if folder.exists() and not any(folder.iterdir()):
        folder.rmdir()
    ico = paths.DATA_DIR / "sg-cube.ico"
    if ico.exists():
        ico.unlink()
    return gone


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    if cmd == "install":
        for p in install():
            print("created", p)
        print("\nStart SG-CUBE from the Start menu or the Desktop shortcut.")
    elif cmd == "uninstall":
        for p in uninstall():
            print("removed", p)
    else:
        sys.exit(__doc__)
