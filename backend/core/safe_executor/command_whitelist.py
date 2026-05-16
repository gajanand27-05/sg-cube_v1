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

# Apps that require Windows elevation. Phase 10a blocks these.
# Phase 10b will route them through UAC's runas verb (Windows shows its own
# password prompt — we never see/store the password).
SYSTEM_APPS = {
    "regedit",
    "regedit.exe",
    "services.msc",
    "gpedit.msc",
    "mmc",
    "mmc.exe",
    "control panel",
    "control",
    "control.exe",
    "task manager",
    "taskmgr",
    "taskmgr.exe",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "computer management",
    "compmgmt.msc",
    "device manager",
    "devmgmt.msc",
    "diskmgmt.msc",
    "event viewer",
    "eventvwr",
}


def is_target_dangerous(target: str) -> bool:
    t = target.lower()
    return any(d in t for d in DANGEROUS_TARGETS)


def is_system_app(target: str) -> bool:
    return target.strip().lower() in SYSTEM_APPS


# ── Handlers ─────────────────────────────────────────────────────────────


def handle_open_app(intent: Intent) -> dict:
    target_raw = intent.target.strip()
    target = target_raw.lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}
    if is_target_dangerous(target):
        return {"status": "blocked", "reason": f"dangerous target rejected: {target_raw!r}"}
    if is_system_app(target):
        return {
            "status": "blocked",
            "reason": f"system app '{target_raw}' requires elevation (Phase 10b will gate this with UAC)",
        }

    canonical = OPEN_ALIASES.get(target, target_raw)

    # `start` is a cmd builtin: resolves Start-Menu shortcuts, PATH, and App-Paths
    # registry entries. shell=True is safe here because `canonical` came from a
    # parsed Intent.target, not raw user input concatenated into a shell string —
    # quoting via the format string handles any spaces.
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
