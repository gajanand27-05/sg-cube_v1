import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from backend.core.plugins.base import SGCubePlugin

log = logging.getLogger(__name__)

class PluginManager:
    def __init__(self, plugins_dir: Optional[Path] = None):
        self.plugins_dir = plugins_dir or Path(__file__).parent / "installed"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.plugins: Dict[str, SGCubePlugin] = {}

    def discover(self):
        """Walk the plugins directory and load all SGCubePlugin subclasses."""
        log.info(f"Discovering plugins in {self.plugins_dir}")
        for loader, module_name, is_pkg in pkgutil.iter_modules([str(self.plugins_dir)]):
            try:
                # Dynamically import the module
                module = importlib.import_module(f"backend.core.plugins.installed.{module_name}")
                
                # Look for SGCubePlugin subclasses
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, SGCubePlugin) and 
                        obj is not SGCubePlugin):
                        
                        instance = obj()
                        self.plugins[instance.name] = instance
                        log.info(f"Loaded plugin: {instance.name}")
            except Exception as e:
                log.error(f"Failed to load plugin {module_name}: {e}")

    def get_plugin(self, name: str) -> Optional[SGCubePlugin]:
        return self.plugins.get(name)

# Global instance
manager = PluginManager()
