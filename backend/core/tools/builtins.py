"""Built-in tools — Phase 11a.

Wraps the existing Phase 6/10 handlers so the agent can call them. Importing
this module is what populates the registry; backend.core.agent.agent imports
it eagerly at boot.
"""
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw
from backend.core.tools.registry import tool


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
