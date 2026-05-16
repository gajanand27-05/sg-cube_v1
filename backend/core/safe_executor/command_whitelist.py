import subprocess
from datetime import datetime

from backend.core.orchestrator.llm_layer import Intent

# ── Aliases ──────────────────────────────────────────────────────────────
# user-spoken name -> canonical launch name (consumed by Windows `start`)
OPEN_ALIASES: dict[str, str] = {
    "calculator": "calc",
    "text editor": "notepad",
    "browser": "chrome",
    "google chrome": "chrome",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "code editor": "code",
    "vlc": "vlc",
    "media player": "vlc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
}

# user-spoken name -> Windows .exe name used by taskkill /IM
CLOSE_ALIASES: dict[str, str] = {
    "calc": "Calculator.exe",
    "calculator": "Calculator.exe",
    "notepad": "notepad.exe",
    "chrome": "chrome.exe",
    "browser": "chrome.exe",
    "google chrome": "chrome.exe",
    "code": "Code.exe",
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "firefox": "firefox.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "whatsapp": "WhatsApp.exe",
    "telegram": "Telegram.exe",
    "vlc": "vlc.exe",
    "media player": "vlc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "files": "explorer.exe",
}

# ── Safety filters ───────────────────────────────────────────────────────
DANGEROUS_TARGETS = (
    "system32",
    "regedit",
    "format ",
    "shutdown",
    "rm -rf",
    "del ",
    "..\\",
    "../",
)

# Apps that require Windows elevation. Phase 10b routes these through UAC's
# `runas` verb — Windows shows its own password / consent dialog. We never see
# or store the password.
#
# Map of user-spoken name -> actual launchable command. (e.g. "task manager"
# isn't a real launch token; "taskmgr.exe" is.)
SYSTEM_APP_COMMANDS: dict[str, str] = {
    "regedit": "regedit.exe",
    "regedit.exe": "regedit.exe",
    "registry editor": "regedit.exe",
    "services": "services.msc",
    "services.msc": "services.msc",
    "gpedit": "gpedit.msc",
    "gpedit.msc": "gpedit.msc",
    "group policy editor": "gpedit.msc",
    "mmc": "mmc.exe",
    "mmc.exe": "mmc.exe",
    "control panel": "control.exe",
    "control": "control.exe",
    "control.exe": "control.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "taskmgr.exe": "taskmgr.exe",
    "cmd": "cmd.exe",
    "cmd.exe": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "powershell.exe": "powershell.exe",
    "computer management": "compmgmt.msc",
    "compmgmt.msc": "compmgmt.msc",
    "device manager": "devmgmt.msc",
    "devmgmt.msc": "devmgmt.msc",
    "disk management": "diskmgmt.msc",
    "diskmgmt.msc": "diskmgmt.msc",
    "event viewer": "eventvwr.msc",
    "eventvwr": "eventvwr.msc",
    "eventvwr.msc": "eventvwr.msc",
}
SYSTEM_APPS = set(SYSTEM_APP_COMMANDS.keys())


def is_target_dangerous(target: str) -> bool:
    t = target.lower()
    return any(d in t for d in DANGEROUS_TARGETS)


def is_system_app(target: str) -> bool:
    return target.strip().lower() in SYSTEM_APPS


def _launch_elevated(target_label: str, command: str) -> dict:
    """Trigger Windows UAC for `command`. Windows shows the password / consent
    dialog itself — we never see or handle the password. Blocks until UAC
    resolves (typically 1–30 seconds depending on user response time).
    """
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Start-Process '{command}' -Verb RunAs",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "blocked", "reason": f"UAC prompt timed out for {target_label!r}"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        # PowerShell's Start-Process raises "The operation was canceled by the user."
        # when the UAC dialog is dismissed (Cancel / No).
        if "cancel" in err.lower() or "operation" in err.lower():
            return {"status": "blocked", "reason": f"UAC declined for {target_label!r}"}
        return {"status": "error", "reason": err or "elevation failed"}

    return {"status": "success", "message": f"opened {target_label} (elevated)"}


# ── Handlers ─────────────────────────────────────────────────────────────


def handle_open_app(intent: Intent) -> dict:
    target_raw = intent.target.strip()
    target = target_raw.lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}

    # 1. System app? Route through UAC — Windows handles the password prompt.
    #    This check runs BEFORE is_target_dangerous so that exact-match system
    #    names (regedit, taskmgr, etc.) go through UAC instead of being hard
    #    blocked by the substring filter.
    if is_system_app(target):
        elevated_cmd = SYSTEM_APP_COMMANDS[target]
        return _launch_elevated(target_raw, elevated_cmd)

    # 2. Substring dangerous filter (catches abuse like "open random-regedit-tool").
    if is_target_dangerous(target):
        return {"status": "blocked", "reason": f"dangerous target rejected: {target_raw!r}"}

    # 3. Regular app — `start` resolves Start-Menu shortcuts, PATH, App-Paths.
    canonical = OPEN_ALIASES.get(target, target_raw)
    try:
        subprocess.Popen(f'start "" "{canonical}"', shell=True)
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    return {"status": "success", "message": f"opened {target_raw}"}


def handle_close_app(intent: Intent) -> dict:
    target_raw = intent.target.strip()
    target = target_raw.lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}
    if is_target_dangerous(target):
        return {"status": "blocked", "reason": f"dangerous target rejected: {target_raw!r}"}

    proc = CLOSE_ALIASES.get(target, f"{target_raw}.exe")

    try:
        result = subprocess.run(
            ["taskkill", "/IM", proc, "/F"],
            capture_output=True, text=True, check=False,
        )
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    if result.returncode == 0:
        return {"status": "success", "message": f"closed {target_raw}"}

    # Fallback: if we constructed the .exe name ourselves and it failed,
    # try the target verbatim once.
    if target not in CLOSE_ALIASES and proc != target_raw:
        try:
            r2 = subprocess.run(
                ["taskkill", "/IM", target_raw, "/F"],
                capture_output=True, text=True, check=False,
            )
            if r2.returncode == 0:
                return {"status": "success", "message": f"closed {target_raw}"}
        except Exception:
            pass

    msg = (result.stderr or result.stdout).strip() or "taskkill failed"
    return {"status": "error", "reason": msg}


def handle_get_time(_intent: Intent) -> dict:
    return {"status": "success", "message": datetime.now().strftime("%I:%M %p")}


def handle_unknown(_intent: Intent) -> dict:
    return {"status": "blocked", "reason": "intent action is 'unknown'"}


HANDLERS = {
    "open_app": handle_open_app,
    "close_app": handle_close_app,
    "get_time": handle_get_time,
    "unknown": handle_unknown,
}
