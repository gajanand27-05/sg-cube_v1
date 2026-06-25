"""Built-in tools.

Importing this module populates the registry with every shipped tool.
backend.core.agent.agent imports it eagerly at boot.

- Phase 11a tools defined here (wrap the Phase 6/10 handlers).
- Phase 11b tools live in dedicated modules under backend.core.tools.* —
  their @tool decorators run when their module is imported below.
"""
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw
from backend.core.tools.registry import SecurityLevel, ToolResult, tool


@tool(security=SecurityLevel.SAFE)
def respond(text: str) -> ToolResult:
    """Speak `text` as the final answer to the user. Use this to end the
    conversation after other tools have run, or to answer factual questions
    directly. The agent treats calls to this tool as the terminating step."""
    return ToolResult.success(text)


@tool(security=SecurityLevel.SAFE)
def open_app(name: str) -> ToolResult:
    """Open a desktop application by name. ANY installed app works
    (notepad, chrome, firefox, spotify, discord, whatsapp, vscode, vlc, ...).
    System apps (regedit, task manager, powershell) trigger a Windows UAC
    consent dialog before launching."""
    res = cw.handle_open_app(Intent(action="open_app", target=name))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )


@tool(security=SecurityLevel.SAFE)
def close_app(name: str) -> ToolResult:
    """Close a running desktop application by name."""
    res = cw.handle_close_app(Intent(action="close_app", target=name))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )


@tool(security=SecurityLevel.SAFE)
def play_youtube(query: str) -> ToolResult:
    """Play the FIRST YouTube search result for `query` in the default
    browser. Use this whenever the user says "play <something>" — it's the
    closest thing to JARVIS playing music for you."""
    res = cw.handle_play_youtube(Intent(action="play_youtube", target=query))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )


@tool(security=SecurityLevel.SAFE)
def search_web(query: str, engine: str = "google") -> ToolResult:
    """Open a web search for `query` in the default browser.
    `engine` is "google" (default) or "youtube"."""
    if engine.lower() == "youtube":
        res = cw.handle_search_youtube(Intent(action="search_youtube", target=query))
    else:
        res = cw.handle_search_google(Intent(action="search_google", target=query))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )


@tool(security=SecurityLevel.SAFE)
def open_url(url: str) -> ToolResult:
    """Open a URL or domain (e.g. "github.com" or "https://example.com")
    in the default browser."""
    res = cw.handle_open_url(Intent(action="open_url", target=url))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )


@tool(security=SecurityLevel.SAFE)
def get_time() -> ToolResult:
    """Return the current local time, formatted for speaking aloud."""
    res = cw.handle_get_time(Intent(action="get_time", target=""))
    return ToolResult(
        status=res["status"],
        message=res.get("message"),
        reason=res.get("reason"),
        data=res.get("args") or {}
    )
