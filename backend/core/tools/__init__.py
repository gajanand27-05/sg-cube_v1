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

# unsaved_state is a helper for close_app's confirm_if guard, not a tool
# module — it declares no @tool and has nothing to discover.
_TOOL_MODULES_BLACKLIST = {"__init__", "registry", "sandbox", "llm_helper", "unsaved_state"}

# modname -> import error, for every tool module that did not load.
#
# Swallowing the ImportError is the right call — one broken module must not
# take down the other 28 — but until now the only trace was a log.warning
# nobody reads, and the consequence is severe and silent: every @tool in that
# module is absent from REGISTRY, so the planner is never told the capability
# exists and the assistant simply cannot do that thing. It does not error, it
# does not decline; the tool is not in its world. preflight.check_tool_modules
# reports this, which is the difference between a swallowed failure and a
# recorded one.
FAILED_TOOL_MODULES: dict[str, str] = {}


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
            FAILED_TOOL_MODULES.pop(modname, None)
        except Exception as e:
            FAILED_TOOL_MODULES[modname] = f"{type(e).__name__}: {e}"
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
