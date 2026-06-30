"""Capability protocol and types — unified interface for all executable actions."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

from backend.core.tools.registry import SecurityLevel


class CapabilitySource(str, Enum):
    """Where the capability comes from."""
    NATIVE = "native"       # @tool function
    PLUGIN = "plugin"       # user plugin
    MCP = "mcp"             # MCP server
    REST = "rest"           # REST API endpoint
    SHELL = "shell"         # shell command
    AGENT = "agent"         # sub-agent


@dataclass
class Capability:
    """Unified capability interface — planner asks 'what can do X?'"""
    name: str
    description: str
    schema: dict[str, Any]           # JSON schema for args
    source: CapabilitySource = CapabilitySource.NATIVE
    security: SecurityLevel = SecurityLevel.SAFE
    tags: list[str] = field(default_factory=list)  # e.g., ["file", "write", "dangerous"]
    metadata: dict = field(default_factory=dict)
    
    @abstractmethod
    async def execute(self, args: dict, request_id: str) -> Any:
        """Execute the capability. Implemented by subclass."""
        ...


@dataclass
class NativeToolCapability(Capability):
    """Wraps a @tool function."""
    tool_name: str = ""
    
    async def execute(self, args: dict, request_id: str) -> Any:
        from backend.core.tools.registry import call as call_tool
        return await call_tool(self.tool_name, args, request_id=request_id)


@dataclass
class MCPCapability(Capability):
    """Wraps an MCP server tool."""
    server_name: str = ""
    remote_tool_name: str = ""
    
    async def execute(self, args: dict, request_id: str) -> Any:
        # TODO: Implement MCP client call
        raise NotImplementedError("MCP client not yet wired")


@dataclass
class RESTCapability(Capability):
    """Wraps a REST API endpoint."""
    endpoint: str = ""
    method: str = "POST"
    
    async def execute(self, args: dict, request_id: str) -> Any:
        # TODO: Implement REST call
        raise NotImplementedError("REST capability not yet wired")


@dataclass
class ShellCapability(Capability):
    """Wraps a shell command."""
    command_template: str = ""
    
    async def execute(self, args: dict, request_id: str) -> Any:
        # TODO: Implement safe shell execution
        raise NotImplementedError("Shell capability not yet wired")