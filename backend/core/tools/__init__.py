"""Tool registry — importing this module populates REGISTRY with all built-in tools.

Phase B: Uses pkgutil.iter_modules for auto-discovery instead of manual imports.
User plugins in backend/plugins/ are also auto-imported.
"""
import importlib
import logging
import pkgutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_TOOL_MODULES_BLACKLIST = {"__init__", "registry", "sandbox", "llm_helper", "builtins"}


def _discover_tools() -> None:
    """Auto-import all modules in backend.core.tools to trigger @tool decorators."""
    package_name = "backend.core.tools"
    package = sys.modules.get(package_name)
    if package is None:
        return
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return

    for importer, modname, is_pkg in pkgutil.iter_modules(package_path):
        if modname in _TOOL_MODULES_BLACKLIST or is_pkg:
            continue
        try:
            importlib.import_module(f"{package_name}.{modname}")
            log.debug("Discovered tool module: %s", modname)
        except Exception as e:
            log.warning("Failed to import tool module %s: %s", modname, e)


def _discover_plugins() -> None:
    """Auto-import any .py files dropped in backend/plugins/."""
    plugins_path = Path(__file__).resolve().parents[2] / "plugins"
    if not plugins_path.is_dir():
        return

    sys.path.insert(0, str(plugins_path.parent))
    for fpath in plugins_path.iterdir():
        if fpath.suffix != ".py" or fpath.name == "__init__.py":
            continue
        modname = f"plugins.{fpath.stem}"
        try:
            importlib.import_module(modname)
            log.info("Loaded user plugin: %s", fpath.name)
        except Exception as e:
            log.warning("Failed to load user plugin %s: %s", fpath.name, e)


# ── Bootstrap ──────────────────────────────────────────────────────────
# 1. Load builtins (Phase 11a tools defined directly).
from backend.core.tools import builtins  # noqa: F401

# 2. Auto-discover and import all tool sub-modules.
_discover_tools()

# 3. Auto-discover and import any user plugins.
_discover_plugins()
