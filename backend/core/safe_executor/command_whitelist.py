import subprocess
from datetime import datetime

from backend.core.orchestrator.llm_layer import Intent

ALLOWED_OPEN: dict[str, str] = {
    "notepad": "notepad",
    "calc": "calc",
    "chrome": "start chrome",
    "code": "code",
}

ALLOWED_CLOSE: dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "Calculator.exe",
    "chrome": "chrome.exe",
    "code": "Code.exe",
}

DANGEROUS_TARGETS = ("system32", "regedit", "format ", "shutdown", "rm -rf", "del ", "..\\", "../")


def is_target_dangerous(target: str) -> bool:
    t = target.lower()
    return any(d in t for d in DANGEROUS_TARGETS)


def handle_open_app(intent: Intent) -> dict:
    target = intent.target.strip().lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}
    if target not in ALLOWED_OPEN:
        return {"status": "blocked", "reason": f"app '{target}' not in open allowlist"}
    cmd = ALLOWED_OPEN[target]
    try:
        subprocess.Popen(cmd, shell=True)
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    return {"status": "success", "message": f"opened {target}"}


def handle_close_app(intent: Intent) -> dict:
    target = intent.target.strip().lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}
    if target not in ALLOWED_CLOSE:
        return {"status": "blocked", "reason": f"app '{target}' not in close allowlist"}
    proc_name = ALLOWED_CLOSE[target]
    try:
        result = subprocess.run(
            ["taskkill", "/IM", proc_name, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "taskkill failed"
        return {"status": "error", "reason": msg}
    return {"status": "success", "message": f"closed {target}"}


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
