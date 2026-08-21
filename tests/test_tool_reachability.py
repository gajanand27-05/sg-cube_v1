"""Every @tool must actually reach the planner.

The planner's entire idea of what it can do comes from
`context.capabilities`, which is `capability_registry.all()`, which is built by
walking `REGISTRY`, which is populated by @tool decorators, which only fire if
the defining module gets imported. Four hops, and each one has failed here
before — main.py's own comment records the time capabilities were never
discovered at all and the planner fell through to final_response for every
rule-engine miss.

The live failure mode is the import swallow in backend.core.tools: one module
raising on import is caught so the other 28 survive, which is right, but every
tool in it then silently disappears from the planner's world. The assistant
does not error and does not decline — it behaves exactly like a model that
chose not to use the tool. Nothing distinguishes those two from the outside.
"""
import importlib
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import backend.core.tools as tools_pkg
from backend.core.caps.registry import capability_registry
from backend.core.preflight import PreflightStatus, check_tool_modules
from backend.core.tools.registry import REGISTRY


def test_no_tool_module_failed_to_import():
    assert tools_pkg.FAILED_TOOL_MODULES == {}, (
        "these tool modules did not import, so none of their @tools exist as "
        "far as the planner is concerned: " + repr(tools_pkg.FAILED_TOOL_MODULES)
    )


def test_every_registered_tool_is_reachable_as_a_capability():
    """REGISTRY is not what the planner reads — capability_registry is. A tool
    present in one and absent from the other is invisible in practice."""
    capability_registry.discover()
    cap_names = {c.name for c in capability_registry.all()}
    unreachable = sorted(set(REGISTRY) - cap_names)
    assert not unreachable, (
        f"{len(unreachable)} tool(s) exist in REGISTRY but are not capabilities, "
        f"so the planner is never told about them: {unreachable}"
    )


def test_the_check_can_see_real_tools():
    """A count assertion, because every test above passes trivially if
    discovery silently produced nothing at all."""
    assert len(REGISTRY) > 50, f"only {len(REGISTRY)} tools registered — discovery looks broken"
    # Named spot-checks across several modules, so a partial import failure
    # cannot hide behind a healthy-looking total.
    # describe_scene/ocr_read were the phone-camera pair and went with that
    # subsystem; describe_screen/ocr_screen are the surviving screen tools.
    for name in ("get_time", "describe_screen", "ocr_screen"):
        assert name in REGISTRY, f"{name} missing from REGISTRY"


def test_preflight_reports_ok_when_every_module_imported():
    result = check_tool_modules()
    assert result.status is PreflightStatus.OK, result.message
    assert result.detail["tools_registered"] == len(REGISTRY)


def test_preflight_reports_degraded_when_a_module_fails_to_import(tmp_path, monkeypatch):
    """Induce a REAL import failure rather than poking FAILED_TOOL_MODULES:
    the thing under test is that the discovery loop records what it swallows,
    and setting the dict by hand would assert nothing about the loop."""
    broken = Path(tools_pkg.__path__[0]) / "_broken_probe.py"
    broken.write_text("raise RuntimeError('induced import failure')\n", encoding="utf-8")
    try:
        tools_pkg._discover_tools()
        assert "_broken_probe" in tools_pkg.FAILED_TOOL_MODULES, (
            "the discovery loop swallowed an import error without recording it — "
            "which is the invisible-failure state this whole file is about"
        )
        result = check_tool_modules()
        assert result.status is PreflightStatus.DEGRADED
        assert "_broken_probe" in result.message
        assert "RuntimeError" in result.detail["failed"]["_broken_probe"]
    finally:
        broken.unlink(missing_ok=True)
        tools_pkg.FAILED_TOOL_MODULES.pop("_broken_probe", None)
        sys.modules.pop("backend.core.tools._broken_probe", None)
        importlib.invalidate_caches()

    # The failure must not linger once the module is gone.
    assert check_tool_modules().status is PreflightStatus.OK


def test_a_recovered_module_clears_its_recorded_failure(tmp_path):
    """Otherwise a transient failure pins DEGRADED forever and the check
    becomes noise people learn to ignore."""
    probe = Path(tools_pkg.__path__[0]) / "_recovering_probe.py"
    probe.write_text("raise RuntimeError('first attempt fails')\n", encoding="utf-8")
    try:
        tools_pkg._discover_tools()
        assert "_recovering_probe" in tools_pkg.FAILED_TOOL_MODULES

        probe.write_text("# fixed\n", encoding="utf-8")
        importlib.invalidate_caches()
        tools_pkg._discover_tools()
        assert "_recovering_probe" not in tools_pkg.FAILED_TOOL_MODULES, (
            "module imports fine now but is still recorded as failed"
        )
    finally:
        probe.unlink(missing_ok=True)
        tools_pkg.FAILED_TOOL_MODULES.pop("_recovering_probe", None)
        sys.modules.pop("backend.core.tools._recovering_probe", None)
        importlib.invalidate_caches()
