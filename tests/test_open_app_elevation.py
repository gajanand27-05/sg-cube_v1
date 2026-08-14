"""Opening a Windows shell app must not raise UAC unless the app needs admin.

The whole SYSTEM_APP_COMMANDS table used to route through Start-Process
-Verb RunAs. That made "open command prompt" fail outright: the consent dialog
blocks until a human answers, runtime.run_tool cancels the tool at 30s, and the
user got "Execution timed out after 30.0s" with a modal dialog left on screen.
Found in a live demo rehearsal, not by a unit test — hence this file.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import runtime as runtime_module
from backend.core.safe_executor import command_whitelist as cw
from backend.core.orchestrator.llm_layer import Intent

# The apps a reviewer is most likely to ask for out loud. None of these need
# admin rights, so none of them may reach the elevation path.
EVERYDAY = ["cmd", "command prompt", "powershell", "task manager", "control panel"]


@pytest.mark.parametrize("spoken", EVERYDAY)
def test_everyday_apps_never_trigger_uac(spoken, monkeypatch):
    elevated = []
    monkeypatch.setattr(cw, "_launch_elevated",
                        lambda label, command: elevated.append(command) or {"status": "success"})
    launched = []
    monkeypatch.setattr(cw.subprocess, "Popen", lambda *a, **k: launched.append(a[0]))

    res = cw.handle_open_app(Intent(action="open_app", target=spoken, args={}))

    assert not elevated, f"{spoken!r} was routed through UAC but needs no elevation"
    assert res["status"] == "success", res
    assert launched, f"{spoken!r} produced no launch at all"


def test_apps_that_really_need_admin_still_elevate(monkeypatch):
    elevated = []
    monkeypatch.setattr(cw, "_launch_elevated",
                        lambda label, command: elevated.append(command) or {"status": "success"})
    monkeypatch.setattr(cw.subprocess, "Popen", lambda *a, **k: None)

    cw.handle_open_app(Intent(action="open_app", target="disk management", args={}))
    assert elevated == ["diskmgmt.msc"], "admin-only app lost its elevation"


def test_uac_wait_fits_inside_the_tool_budget():
    """A UAC wait longer than run_tool's timeout can never be reached: the
    outer cancel fires first and replaces the real reason with a generic
    timeout. This was 120s vs 30s."""
    import inspect

    budget = inspect.signature(runtime_module.Runtime.run_tool).parameters["timeout"].default
    assert cw.UAC_WAIT_S < budget, (
        f"UAC wait {cw.UAC_WAIT_S}s >= run_tool budget {budget}s; the elevation "
        "path's own timeout message is unreachable"
    )


def test_every_elevated_command_is_a_real_table_entry():
    """NEEDS_ELEVATION holds launch commands, not spoken names. A typo here
    silently downgrades an admin app to an unelevated launch."""
    known = set(cw.SYSTEM_APP_COMMANDS.values())
    unknown = cw.NEEDS_ELEVATION - known
    assert not unknown, f"not launch commands in SYSTEM_APP_COMMANDS: {sorted(unknown)}"
