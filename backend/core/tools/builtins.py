"""Built-in tools.

Importing this module populates the registry with every shipped tool.
backend.core.agent.agent imports it eagerly at boot.

- Phase 11a tools defined here (wrap the Phase 6/10 handlers).
- Phase 11b tools live in dedicated modules under backend.core.tools.* —
  their @tool decorators run when their module is imported below.
"""
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw
from backend.core.tools.registry import tool


@tool
def respond(text: str) -> dict:
    """Speak `text` as the final answer to the user. Use this to end the
    conversation after other tools have run, or to answer factual questions
    directly. The agent treats calls to this tool as the terminating step."""
    return {"status": "success", "message": text}

# Phase 11b: importing these modules registers their @tool functions.
from backend.core.tools import audio as _audio  # noqa: F401
from backend.core.tools import display as _display  # noqa: F401
from backend.core.tools import files as _files  # noqa: F401
from backend.core.tools import system_info as _system_info  # noqa: F401
from backend.core.tools import windowing as _windowing  # noqa: F401

# Phase 11c — productivity (notes, reminders, clipboard, messaging)
from backend.core.tools import comms as _comms  # noqa: F401
from backend.core.tools import notes as _notes  # noqa: F401
from backend.core.tools import reminders as _reminders  # noqa: F401

# Phase 11d — information feeds (weather, stocks, crypto, news, trending, briefing)
from backend.core.tools import finance as _finance  # noqa: F401
from backend.core.tools import news as _news  # noqa: F401
from backend.core.tools import weather as _weather  # noqa: F401


@tool
def open_app(name: str) -> dict:
    """Open a desktop application by name. ANY installed app works
    (notepad, chrome, firefox, spotify, discord, whatsapp, vscode, vlc, ...).
    System apps (regedit, task manager, powershell) trigger a Windows UAC
    consent dialog before launching."""
    return cw.handle_open_app(Intent(action="open_app", target=name))


@tool
def close_app(name: str) -> dict:
    """Close a running desktop application by name."""
    return cw.handle_close_app(Intent(action="close_app", target=name))


@tool
def play_youtube(query: str) -> dict:
    """Play the FIRST YouTube search result for `query` in the default
    browser. Use this whenever the user says "play <something>" — it's the
    closest thing to JARVIS playing music for you."""
    return cw.handle_play_youtube(Intent(action="play_youtube", target=query))


@tool
def search_web(query: str, engine: str = "google") -> dict:
    """Open a web search for `query` in the default browser.
    `engine` is "google" (default) or "youtube"."""
    if engine.lower() == "youtube":
        return cw.handle_search_youtube(Intent(action="search_youtube", target=query))
    return cw.handle_search_google(Intent(action="search_google", target=query))


@tool
def open_url(url: str) -> dict:
    """Open a URL or domain (e.g. "github.com" or "https://example.com")
    in the default browser."""
    return cw.handle_open_url(Intent(action="open_url", target=url))


@tool
def get_time() -> dict:
    """Return the current local time, formatted for speaking aloud."""
    return cw.handle_get_time(Intent(action="get_time", target=""))
