"""Capability Registry — discovers and manages all executable capabilities."""
import logging
from typing import Any

from backend.core.caps.types import (
    Capability, CapabilitySource, NativeToolCapability,
    MCPCapability, RESTCapability, ShellCapability
)
from backend.core.tools.registry import REGISTRY, all_schemas
from backend.core.plugins.manager import plugin_manager

log = logging.getLogger(__name__)


class CapabilityRegistry:
    """Central registry of all capabilities — native tools, plugins, MCP, REST, shell."""
    
    def __init__(self):
        self._capabilities: dict[str, Capability] = {}
        self._discovered = False
    
    def discover(self) -> None:
        """Discover all capabilities from all sources."""
        if self._discovered:
            return
        
        # 1. Native tools (from @tool decorators)
        self._discover_native_tools()
        
        # 2. User plugins
        self._discover_plugins()
        
        # 3. MCP servers (if configured)
        self._discover_mcp()
        
        # 4. REST endpoints (if configured)
        self._discover_rest()
        
        # 5. Shell commands (if configured)
        self._discover_shell()
        
        self._discovered = True
        log.info(f"Capability registry discovered {len(self._capabilities)} capabilities")
    
    def _discover_native_tools(self) -> None:
        """Register all native @tool functions."""
        for name, tool in REGISTRY.items():
            cap = NativeToolCapability(
                name=name,
                description=tool.description,
                schema=tool.schema,
                source=CapabilitySource.NATIVE,
                security=tool.security,
                tool_name=name,
            )
            self._capabilities[name] = cap
    
    def _discover_plugins(self) -> None:
        """Register capabilities from user plugins."""
        if not plugin_manager.discovered:
            plugin_manager.discover()
        
        for plugin_name, plugin in plugin_manager.plugins.items():
            # Register plugin as a single capability that wraps its execute method
            cap_name = f"plugin.{plugin_name}"
            from backend.core.caps.types import Capability, CapabilitySource
            
            class PluginCapability(Capability):
                def __init__(self):
                    super().__init__(
                        name=cap_name,
                        description=f"Plugin: {plugin_name}",
                        schema={"type": "object", "properties": {}},
                        source=CapabilitySource.PLUGIN,
                    )
                    self._plugin = plugin
                
                async def execute(self, args: dict, request_id: str) -> Any:
                    from backend.core.plugins.base import PluginContext
                    ctx = PluginContext(
                        request_id=request_id,
                        run_tool=lambda name, args: None,  # placeholder
                        log=logging.getLogger("plugin").info,
                    )
                    return await self._plugin.execute(ctx, **args)
            
            self._capabilities[cap_name] = PluginCapability()
    
    def _discover_mcp(self) -> None:
        """Register MCP server tools (placeholder)."""
        # TODO: Connect to MCP client when available
        pass
    
    def _discover_rest(self) -> None:
        """Register REST API capabilities (placeholder)."""
        # TODO: Load from config
        pass
    
    def _discover_shell(self) -> None:
        """Register shell command capabilities (placeholder)."""
        # TODO: Load from config
        pass
    
    def get(self, name: str) -> Capability | None:
        """Get a capability by name."""
        return self._capabilities.get(name)
    
    def find(self, query: str, tags: list[str] | None = None) -> list[Capability]:
        """Find capabilities matching query and/or tags."""
        query = query.lower()
        results = []
        for cap in self._capabilities.values():
            if query in cap.name.lower() or query in cap.description.lower():
                if tags is None or all(t in cap.tags for t in tags):
                    results.append(cap)
        return results
    
    def all(self) -> list[Capability]:
        """Get all capabilities."""
        return list(self._capabilities.values())
    
    def by_source(self, source: CapabilitySource) -> list[Capability]:
        """Get capabilities by source."""
        return [c for c in self._capabilities.values() if c.source == source]
    
    def get_schemas(self) -> list[dict]:
        """Get all capability schemas for LLM prompt."""
        return [c.schema for c in self._capabilities.values()]


# Global instance
capability_registry = CapabilityRegistry()