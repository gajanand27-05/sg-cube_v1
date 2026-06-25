"""Phase G3: Example user plugin for SG_CUBE.

Drop any .py file with @tool functions into backend/plugins/ and it will
be auto-discovered at boot — zero configuration required.

To activate this plugin, copy it to backend/plugins/ (it's already there).
Restart the daemon and the `hello_world` tool will appear in the registry.
"""
from backend.core.tools.registry import SecurityLevel, ToolResult, tool


@tool(security=SecurityLevel.SAFE)
def hello_world(name: str = "SG_CUBE") -> ToolResult:
    """A friendly greeting from a user plugin. Provide a name to greet."""
    return ToolResult.success(f"Hello, {name}! This is a user plugin loaded from backend/plugins/.")
