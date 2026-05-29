import logging
import abc
from typing import Any, Optional
from backend.core.tools.registry import ToolResult

log = logging.getLogger(__name__)

class PluginContext:
    """Provides restricted access to system resources for plugins."""
    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id

    async def run_tool(self, name: str, **kwargs) -> ToolResult:
        """Plugins should call tools via this method to maintain audit logs."""
        from backend.core.tools.registry import call as call_tool
        return await call_tool(name, kwargs, request_id=self.request_id)

    def log(self, message: str, level: int = logging.INFO):
        log.log(level, f"[Plugin] {message}")

class SGCubePlugin(abc.ABC):
    """Base class for all SG_CUBE plugins."""
    
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for the plugin (e.g. 'Spotify')."""
        pass

    @abc.abstractmethod
    async def execute(self, ctx: PluginContext, **kwargs) -> Any:
        """Main entry point for plugin execution."""
        pass
