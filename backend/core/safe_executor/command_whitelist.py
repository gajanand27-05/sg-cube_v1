import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from backend.core.orchestrator.llm_layer import Intent

log = logging.getLogger(__name__)

# ── Human-language hints ────────────────────────────────────────────────
# Spoken phrases that won't naturally substring-match a Start Menu name
# (because the spoken word is a generic concept, not a brand). Anything
# brand-named (whatsapp, spotify, chrome, calculator, ...) is resolved at
# runtime — no per-app code lives here.
OPEN_HINTS: dict[str, str] = {
    "browser": "chrome",  # falls back to whatever browser the user has installed
    "files": "file explorer",
    "file explorer": "file explorer",
    "text editor": "notepad",
    "code editor": "code",
}

CLOSE_HINTS: dict[str, str] = {
    "browser": "chrome",
    "files": "explorer",
    "file explorer": "explorer",
    "text editor": "notepad",
}

# ── Chrome profile support ─────────────────────────────────────────
# Reads Chrome's Local State to auto-discover named profiles so the
# assistant can open Chrome with a specific account/profile.
# Data format: %LOCALAPPDATA%\Google\Chrome\User Data\Local State
#   → profile.info_cache."Profile 1".name = "Work"
#   → profile.info_cache."Default".name = "Gajanand V"


def _get_chrome_profiles() -> dict[str, str]:
    """Return {display_name_lower: profile_directory} from Chrome Local State.

    Returns empty dict if Chrome isn't installed or the file can't be read.
    """
    path = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Local State"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = (data.get("profile") or {}).get("info_cache") or {}
        return {v.get("name", k).lower(): k for k, v in info.items() if v.get("name")}
    except Exception:
        log.warning("Failed to read Chrome profiles from %s", path)
        return {}


def _resolve_chrome_path() -> Path:
    """Find chrome.exe — tries common install paths."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("chrome.exe not found in any standard location")

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


# ── Generic app resolution (Start Menu + running processes) ─────────────

# Cached list of (Name, AppID) tuples from PowerShell's Get-StartApps.
# Populated lazily on first open. Use refresh_apps_cache() if a new app
# was installed after the daemon started.
_apps_cache: list[tuple[str, str]] | None = None


def _load_start_apps() -> list[tuple[str, str]]:
    """Enumerate every installed app (UWP + Win32 + Start Menu shortcuts)
    via PowerShell's Get-StartApps. Returns [(Name, AppID), ...].
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except Exception as e:
        log.warning("Get-StartApps failed: %s", e)
        return []
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    # Single result comes back as a dict, multiple as a list.
    if isinstance(data, dict):
        data = [data]
    return [(d.get("Name", ""), d.get("AppID", "")) for d in data if d.get("AppID")]


def _get_apps_cache() -> list[tuple[str, str]]:
    global _apps_cache
    if _apps_cache is None:
        _apps_cache = _load_start_apps()
    return _apps_cache


def refresh_apps_cache() -> None:
    """Re-scan installed apps. Call this if the user installs something new
    while the daemon is running."""
    global _apps_cache
    _apps_cache = _load_start_apps()


def _match_app(query: str, candidates: list[str]) -> str | None:
    """Pick the best app name from `candidates` for the spoken `query`.

    Match order: exact (case-insensitive) > query is a substring of name
    > name is a substring of query. Ties broken by shortest name.
    """
    q = query.strip().lower()
    if not q or not candidates:
        return None
    # 1. Exact
    for n in candidates:
        if n.lower() == q:
            return n
    # 2. Query is substring of name ("calc" -> "Calculator", "whatsapp" -> "WhatsApp")
    matches = [n for n in candidates if q in n.lower()]
    if matches:
        return min(matches, key=len)
    # 3. Name is substring of query ("google chrome" -> "Chrome")
    matches = [n for n in candidates if n.lower() in q]
    if matches:
        return max(matches, key=len)
    return None


def _resolve_app_id(query: str) -> tuple[str, str] | None:
    """Resolve a user query to (display_name, AppID) using Get-StartApps."""
    apps = _get_apps_cache()
    if not apps:
        return None
    names = [name for name, _ in apps]
    best = _match_app(query, names)
    if best is None:
        return None
    for name, app_id in apps:
        if name == best:
            return name, app_id
    return None


def _running_proc_names() -> list[str]:
    """Snapshot of running process names (e.g. ['chrome.exe', 'CalculatorApp.exe'])."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except Exception:
        return []
    procs: list[str] = []
    for line in (result.stdout or "").splitlines():
        if line.startswith('"'):
            name = line.split('","')[0].strip('"')
            if name:
                procs.append(name)
    return procs


def _find_running_proc(query: str) -> str | None:
    """Pick the best running .exe name matching `query`. Handles cases where
    the spoken name doesn't equal the process name (calculator -> CalculatorApp.exe,
    whatsapp -> WhatsApp.Root.exe).
    """
    q = query.strip().lower().replace(" ", "")
    if not q:
        return None
    procs = _running_proc_names()
    if not procs:
        return None
    # Normalize: drop ".exe" and any dotted suffixes for the matching key only.
    def base(p: str) -> str:
        b = p.lower()
        if b.endswith(".exe"):
            b = b[:-4]
        return b

    # 1. Exact base match
    for p in procs:
        if base(p) == q:
            return p
    # 2. Query is substring of base ("calculator" in "calculatorapp")
    matches = [p for p in procs if q in base(p)]
    if matches:
        return min(matches, key=lambda p: len(base(p)))
    # 3. Base is substring of query ("chrome" in "google chrome")
    matches = [p for p in procs if base(p) in q]
    if matches:
        return max(matches, key=lambda p: len(base(p)))
    return None


# ── Handlers ─────────────────────────────────────────────────────────────


def handle_open_app(intent: Intent) -> dict:
    target_raw = intent.target.strip()
    target = target_raw.lower()
    if not target:
        return {"status": "blocked", "reason": "empty target"}

    # 1. System app? Route through UAC — Windows handles the password prompt.
    if is_system_app(target):
        return _launch_elevated(target_raw, SYSTEM_APP_COMMANDS[target])

    # 2. Substring dangerous filter (blocks abuse like "open random-regedit-tool").
    if is_target_dangerous(target):
        return {"status": "blocked", "reason": f"dangerous target rejected: {target_raw!r}"}

    # ── Chrome profile branch ──────────────────────────────────────────
    profile_arg = (intent.args or {}).get("profile", "")
    if profile_arg and ("chrome" in target or "google chrome" in target):
        profiles = _get_chrome_profiles()
        if not profiles:
            return {"status": "error", "reason": "no Chrome profiles found"}
        match = profile_arg.lower()
        dir_name = profiles.get(match)
        if not dir_name:
            close = ", ".join(sorted(profiles))
            return {"status": "error", "reason": f"no Chrome profile named '{profile_arg}'. Available: {close}"}
        try:
            subprocess.Popen(["chrome.exe", f"--profile-directory={dir_name}"])
        except FileNotFoundError:
            try:
                path = _resolve_chrome_path()
                subprocess.Popen([str(path), f"--profile-directory={dir_name}"])
            except Exception as e:
                return {"status": "error", "reason": str(e)}
        return {"status": "success", "message": f"opened Chrome ({profile_arg})"}

    # 3. Resolve via Get-StartApps. Apply OPEN_HINTS first for human-language
    #    phrases that won't naturally match a Start Menu name ("browser", "files").
    query = OPEN_HINTS.get(target, target_raw)
    resolved = _resolve_app_id(query)
    if resolved is not None:
        name, app_id = resolved
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
        except Exception as e:
            return {"status": "error", "reason": str(e)}
        return {"status": "success", "message": f"opened {name}"}

    # 4. Last-resort fallback: hand the raw target to `start` (catches things
    #    not in Get-StartApps — typed paths, App-Paths registrations, etc.).
    try:
        subprocess.Popen(f'start "" "{target_raw}"', shell=True)
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

    # Apply CLOSE_HINTS for human-language terms, then fuzzy-match against
    # the live process list.
    query = CLOSE_HINTS.get(target, target_raw)
    proc = _find_running_proc(query)
    if proc is None:
        return {"status": "blocked", "reason": f"{target_raw!r} is not running"}

    try:
        result = subprocess.run(
            ["taskkill", "/IM", proc, "/F"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    if result.returncode == 0:
        return {"status": "success", "message": f"closed {target_raw}"}
    msg = (result.stderr or result.stdout).strip() or "taskkill failed"
    return {"status": "error", "reason": msg}


def handle_get_time(_intent: Intent) -> dict:
    return {"status": "success", "message": datetime.now().strftime("%I:%M %p")}


def handle_unknown(_intent: Intent) -> dict:
    return {"status": "blocked", "reason": "intent action is 'unknown'"}


# ── Phase 10c: in-app actions (web search + YouTube play) ────────────────

def _open_url(url: str) -> dict:
    """Open `url` in the user's default browser via Windows `start`."""
    try:
        subprocess.Popen(f'start "" "{url}"', shell=True)
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    return {"status": "success", "message": url}


def handle_open_url(intent: Intent) -> dict:
    target = intent.target.strip()
    if not target:
        return {"status": "blocked", "reason": "empty URL"}
    if is_target_dangerous(target):
        return {"status": "blocked", "reason": f"dangerous URL rejected: {target!r}"}
    url = target if "://" in target else f"https://{target}"
    return _open_url(url)


def handle_search_google(intent: Intent) -> dict:
    query = intent.target.strip()
    if not query:
        return {"status": "blocked", "reason": "empty search query"}
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    r = _open_url(url)
    if r["status"] == "success":
        r["message"] = f"google search for {query!r}"
    return r


def handle_search_youtube(intent: Intent) -> dict:
    query = intent.target.strip()
    if not query:
        return {"status": "blocked", "reason": "empty search query"}
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    r = _open_url(url)
    if r["status"] == "success":
        r["message"] = f"youtube search for {query!r}"
    return r


def handle_play_youtube(intent: Intent) -> dict:
    """Resolve the first YouTube search result via yt-dlp, then open that
    watch URL in the default browser. Falls back to the search results page
    on network/parse failure."""
    query = intent.target.strip()
    if not query:
        return {"status": "blocked", "reason": "empty play query"}

    fallback_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    try:
        import yt_dlp  # lazy import: keeps daemon startup snappy
    except ImportError:
        return _open_url(fallback_url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "default_search": "ytsearch1",
        "socket_timeout": 10,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception as e:
        log.warning("yt-dlp search failed for %r: %s", query, e)
        r = _open_url(fallback_url)
        if r["status"] == "success":
            r["message"] = f"youtube search for {query!r} (yt-dlp unavailable, opened results page)"
        return r

    entries = (info or {}).get("entries") or []
    if not entries:
        r = _open_url(fallback_url)
        if r["status"] == "success":
            r["message"] = f"no results for {query!r}, opened YouTube search page"
        return r

    first = entries[0]
    vid = first.get("id") or first.get("url")
    title = first.get("title") or query
    if not vid:
        r = _open_url(fallback_url)
        if r["status"] == "success":
            r["message"] = f"could not resolve video id for {query!r}, opened results"
        return r

    watch_url = vid if vid.startswith("http") else f"https://www.youtube.com/watch?v={vid}"
    r = _open_url(watch_url)
    if r["status"] == "success":
        r["message"] = f"playing {title!r}"
    return r


def handle_agent_complete(intent: Intent) -> dict:
    """Synthetic intent emitted by the Phase 11a agent path. The agent has
    already run all the tools internally; the executor is a no-op and just
    surfaces the spoken response for TTS."""
    spoken = (intent.args or {}).get("spoken", "Done.")
    return {"status": "success", "message": spoken}


HANDLERS = {
    "open_app": handle_open_app,
    "close_app": handle_close_app,
    "get_time": handle_get_time,
    "unknown": handle_unknown,
    # Phase 10c
    "open_url": handle_open_url,
    "search_google": handle_search_google,
    "search_youtube": handle_search_youtube,
    "play_youtube": handle_play_youtube,
    # Phase 11a
    "agent_complete": handle_agent_complete,
}
