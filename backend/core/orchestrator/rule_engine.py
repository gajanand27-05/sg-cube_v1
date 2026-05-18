import re
from typing import Callable

from backend.core.orchestrator.llm_layer import Intent

APP_ALIASES = {
    # Built-in
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "text editor": "notepad",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    # Browsers
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "brave": "brave",
    # Dev
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "code": "code",
    "code editor": "code",
    # Media / messaging
    "spotify": "spotify",
    "discord": "discord",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
    "slack": "slack",
    "teams": "teams",
    "microsoft teams": "teams",
    "vlc": "vlc",
    "media player": "vlc",
    "music": "spotify",
    # System (rule layer captures them; executor routes to UAC)
    "registry editor": "regedit",
    "regedit": "regedit",
    "task manager": "task manager",
    "command prompt": "cmd",
    "powershell": "powershell",
}


def _canonical_app(name: str) -> str:
    name = name.strip().lower()
    return APP_ALIASES.get(name, name)


def _open_app(m: re.Match) -> Intent:
    return Intent(action="open_app", target=_canonical_app(m.group("app")))


def _close_app(m: re.Match) -> Intent:
    return Intent(action="close_app", target=_canonical_app(m.group("app")))


def _get_time(_m: re.Match) -> Intent:
    return Intent(action="get_time", target="")


def _play_youtube(m: re.Match) -> Intent:
    return Intent(action="play_youtube", target=m.group("query").strip())


def _search_youtube(m: re.Match) -> Intent:
    return Intent(action="search_youtube", target=m.group("query").strip())


def _search_google(m: re.Match) -> Intent:
    return Intent(action="search_google", target=m.group("query").strip())


# ── Patterns ────────────────────────────────────────────────────────────
# Order matters: most-specific first. The match() function takes the first
# pattern that matches. So "play X on youtube" must be checked before "play X",
# otherwise the latter would greedily swallow the "on youtube" suffix.

RULES: list[tuple[re.Pattern, Callable[[re.Match], Intent]]] = [
    # ── Phase 10c (more specific phrasings first) ──
    (re.compile(r"^play\s+(?P<query>.+?)\s+on\s+youtube$"), _play_youtube),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+?)\s+on\s+youtube$"), _search_youtube),
    (re.compile(r"^show\s+(?:me\s+)?(?P<query>.+?)\s+on\s+youtube$"), _search_youtube),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+?)\s+on\s+google$"), _search_google),
    (re.compile(r"^youtube\s+(?P<query>.+)$"), _search_youtube),
    (re.compile(r"^google\s+(?P<query>.+)$"), _search_google),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+)$"), _search_google),
    (re.compile(r"^play\s+(?P<query>.+)$"), _play_youtube),

    # ── Phases 5/6/10a (apps + time) ──
    (re.compile(r"^(?:open|launch|start)\s+(?P<app>.+?)$"), _open_app),
    (re.compile(r"^(?:close|quit|exit)\s+(?P<app>.+?)$"), _close_app),
    (
        re.compile(
            r"^(?:what(?:\s+is)?\s+the\s+time"
            r"|what\s+time\s+is\s+it"
            r"|current\s+time"
            r"|tell\s+me\s+the\s+time"
            r"|whats\s+the\s+time)$"
        ),
        _get_time,
    ),
]


def match(normalized_text: str) -> Intent | None:
    """Match against normalized (lowercased, depunctuated) text. Returns None on miss."""
    for pattern, factory in RULES:
        m = pattern.match(normalized_text)
        if m:
            return factory(m)
    return None
