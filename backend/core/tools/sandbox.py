import uuid
from typing import Any

from backend.core.events import get_bus
from backend.core.tools.registry import REGISTRY, SecurityLevel, ToolResult


class PermissionDenied(Exception):
    pass


class PendingConfirmation:
    def __init__(self, token: str, tool_name: str, args: dict):
        self.token = token
        self.tool_name = tool_name
        self.args = args


class PermissionGuard:
    """Intercepts tool calls to enforce security levels."""

    def __init__(self):
        self._pending: dict[str, tuple[str, dict]] = {}

    def check(self, name: str, args: dict) -> ToolResult | None:
        """Checks if a tool can be executed. 
        Returns None if OK, or a ToolResult (BLOCKED/PENDING) if not.
        """
        tool = REGISTRY.get(name)
        if not tool:
            return None

        if tool.security == SecurityLevel.CRITICAL:
            # Critical actions are blocked at this level unless the Guardian
            # or a specific confirmation flow handles them.
            return ToolResult.blocked(f"Tool {name!r} is marked CRITICAL and requires manual approval via the Guardian Agent.")

        if tool.security == SecurityLevel.CAUTION:
            token = str(uuid.uuid4())[:8]
            self._pending[token] = (name, args)
            
            # Publish event so the UI can show a confirmation dialog
            get_bus().publish(PendingConfirmation(token, name, args))
            
            return ToolResult.pending(
                confirmation_token=token,
                message=f"I need your confirmation to run {name}. Please say 'confirm {token}' or click OK."
            )

        return None

    def confirm(self, token: str) -> ToolResult:
        """Execute a previously pending tool call."""
        if token not in self._pending:
            return ToolResult.error(f"Invalid or expired confirmation token: {token}")

        name, args = self._pending.pop(token)
        tool = REGISTRY.get(name)
        if not tool:
            return ToolResult.error(f"Tool {name!r} no longer exists.")

        # Bypass check since we have explicit user confirmation now
        return tool(**args)


# Global instance
guard = PermissionGuard()
