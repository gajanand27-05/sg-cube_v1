import logging
from typing import Any
from backend.core.plugins.base import SGCubePlugin, PluginContext

log = logging.getLogger(__name__)

class SpotifyPlugin(SGCubePlugin):
    """Example plugin for Spotify integration."""
    
    @property
    def name(self) -> str:
        return "Spotify"

    async def execute(self, ctx: PluginContext, **kwargs) -> Any:
        """
        Implementation of Spotify commands.
        Example: ctx.execute(action="play", track="Starboy")
        """
        action = kwargs.get("action", "play")
        track = kwargs.get("track", "current")
        
        ctx.log(f"Spotify performing {action} on {track}")
        
        # In a real plugin, we would use a spotify library or API here.
        # We can also call existing tools:
        # await ctx.run_tool("open_app", name="Spotify")
        
        return {
            "status": "success",
            "message": f"Spotify: {action} {track}",
            "plugin": self.name
        }
