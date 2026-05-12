import re
from typing import Callable

from backend.core.orchestrator.llm_layer import Intent

APP_ALIASES = {
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "text editor": "notepad",
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "code": "code",
    "code editor": "code",
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


RULES: list[tuple[re.Pattern, Callable[[re.Match], Intent]]] = [
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
