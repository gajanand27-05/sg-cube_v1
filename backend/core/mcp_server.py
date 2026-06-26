"""Phase E: MCP Protocol Integration.

E1: Expose SG_CUBE tools as an MCP server via SSE.
E2: Consume external MCP servers (filesystem, GitHub, etc.).

Usage:
    # Standalone
    python -m backend.core.mcp_server

    # Via FastAPI (mounted at /mcp in server/main.py)
    from backend.core.mcp_server import mcp_app
    app.mount("/mcp", mcp_app)
"""
import logging
from typing import Optional

from backend.core.tools.registry import REGISTRY

log = logging.getLogger(__name__)

# ── E1: Expose SG_CUBE tools as MCP server ───────────────────────────

_mcp_server = None


def get_mcp_server():
    """Lazy-initialized singleton MCP server."""
    global _mcp_server
    if _mcp_server is not None:
        return _mcp_server
    try:
        from fastmcp import FastMCP

        server = FastMCP("SG_CUBE")

        for name, tool_obj in REGISTRY.items():
            server.add_tool(tool_obj.func)

        _mcp_server = server
        log.info("MCP server created with %d tools", len(REGISTRY))
    except ImportError:
        log.warning("fastmcp not installed — MCP server unavailable")
        _mcp_server = None
    return _mcp_server


def get_mcp_app():
    """Return a Starlette ASGI app for mounting (e.g. in FastAPI).

    Returns None if fastmcp is not installed.
    """
    server = get_mcp_server()
    if server is None:
        return None
    return server.http_app()


mcp_app = get_mcp_app()


# ── E2: Consume external MCP servers ─────────────────────────────────

_external_clients: dict[str, dict] = {}


async def connect_external_server(name: str, url: str) -> dict:
    """Connect to an external MCP server and return its available tools."""
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                _external_clients[name] = {"session": session, "tools": tools}
                return {"status": "connected", "name": name, "tools": [t.name for t in tools.tools]}
    except Exception as e:
        log.error("Failed to connect to external MCP server %s: %s", name, e)
        return {"status": "error", "name": name, "error": str(e)}


async def call_external_tool(server_name: str, tool_name: str, args: dict) -> dict:
    """Call a tool on an external MCP server."""
    client = _external_clients.get(server_name)
    if not client:
        return {"status": "error", "message": f"Not connected to {server_name}"}
    try:
        result = await client["session"].call_tool(tool_name, args)
        return {"status": "success", "result": result.content}
    except Exception as e:
        log.error("External tool call failed: %s", e)
        return {"status": "error", "message": str(e)}


def list_external_servers() -> list[dict]:
    return [
        {"name": name, "tools": [t.name for t in data["tools"].tools]}
        for name, data in _external_clients.items()
    ]


# ── Standalone runner ────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = get_mcp_server()
    if server:
        log.info("Starting SG_CUBE MCP server on http://0.0.0.0:8002/mcp")
        server.run(transport="sse", host="0.0.0.0", port=8002)
    else:
        log.error("Cannot start MCP server: fastmcp not installed")
