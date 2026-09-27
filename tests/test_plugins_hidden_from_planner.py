"""Plugins are loaded but not offered to the planner while nothing can run
them: "plugin.Spotify" was listed as a capability, and no code path executes
a capability, so the planner was shown a tool that could only fail."""
from backend.core.caps.registry import capability_registry
from backend.core.plugins.manager import plugin_manager


def test_no_plugin_capability_reaches_the_planner():
    capability_registry._discovered = False
    capability_registry._capabilities.clear()
    capability_registry.discover()
    assert plugin_manager.plugins, "fixture: the installed plugins should still load"
    assert not [c for c in capability_registry.all() if c.name.startswith("plugin.")]
