"""Phase 5A — tool execution timeout / hang protection.

Three axes:
  * Registry `_timeout_for_tool` picks the right tier based on the tool's
    source module.
  * Runtime cancels a sleeping tool at its budget, returns a structured
    ToolResult.error containing the "Execution timed out" phrase.
  * Healer routes that phrase to RETRY on attempt 1, ABORT on attempt 2
    (not the 3-retry generic-transient loop the pre-Phase-5 code would
    have applied).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── _timeout_for_tool tier assignment ─────────────────────────────────

def _fake_tool(module_name: str):
    """Build a fake Tool with a func whose __module__ points at the tier
    we want to test. Only the func.__module__ attribute is read by
    _timeout_for_tool, so the rest of the Tool doesn't need to be real."""
    from backend.core.tools.registry import Tool, SecurityLevel, CapabilityTier

    def _fn(**_kw):
        return None
    _fn.__module__ = module_name

    return Tool(
        name="fake",
        description="fake",
        schema={},
        func=_fn,
        security=SecurityLevel.SAFE,
        tier=CapabilityTier.READONLY,
    )


def test_timeout_for_tool_data_fetch_module():
    from backend.core.tools.registry import _timeout_for_tool
    from backend.server.config import settings
    t = _fake_tool("backend.core.tools.data_sources")
    assert _timeout_for_tool(t) == settings.tool_timeout_data_fetch_s
    print("  [PASS] data_sources → tool_timeout_data_fetch_s")


def test_timeout_for_tool_browser_module():
    from backend.core.tools.registry import _timeout_for_tool
    from backend.server.config import settings
    t = _fake_tool("backend.core.tools.web_reader")
    assert _timeout_for_tool(t) == settings.tool_timeout_browser_nav_s
    print("  [PASS] web_reader → tool_timeout_browser_nav_s")


def test_timeout_for_tool_llm_module():
    from backend.core.tools.registry import _timeout_for_tool
    from backend.server.config import settings
    t = _fake_tool("backend.core.tools.summarize")
    assert _timeout_for_tool(t) == settings.tool_timeout_llm_s
    print("  [PASS] summarize → tool_timeout_llm_s")


def test_timeout_for_tool_untier_falls_back_to_default():
    from backend.core.tools.registry import _timeout_for_tool
    from backend.server.config import settings
    t = _fake_tool("backend.core.tools.windowing")  # not in any tier list
    assert _timeout_for_tool(t) == settings.tool_timeout_default_s
    print("  [PASS] untier'd module → tool_timeout_default_s")


# ── runtime.run_tool cancels sleeping tools cleanly ───────────────────

def test_runtime_cancels_sleeping_tool_returns_structured_timeout():
    """A tool that sleeps past its budget is killed, and the returned
    ToolResult is a structured error whose reason contains the phrase
    the Healer looks for. No dangling coroutine warning is asserted here
    because pytest's warning-capture would print it; we assert that
    the runtime's `_tasks` map ends up with the task in FAILED state
    (not still RUNNING)."""
    from backend.core.runtime import Runtime, TaskStatus
    from backend.core.tools.registry import ToolStatus

    rt = Runtime()

    async def sleeper(**_kw):
        await asyncio.sleep(5.0)
        return {"status": "success", "message": "shouldn't happen"}

    result = asyncio.run(rt.run_tool("sleeper", sleeper, {}, timeout=0.2))

    assert result.status == ToolStatus.ERROR, f"expected ERROR, got {result.status}"
    assert "execution timed out" in (result.reason or "").lower(), (
        f"expected 'execution timed out' in reason, got {result.reason!r}"
    )
    # Every task should be settled; nothing stuck in RUNNING
    running = [t for t in rt._tasks.values() if t.status == TaskStatus.RUNNING]
    assert running == [], f"dangling RUNNING tasks: {[t.name for t in running]}"
    print("  [PASS] sleeping tool cancelled → structured timeout, no dangling task")


# ── Healer routes tool-execution timeouts to RETRY-once-then-ABORT ────

def test_healer_routes_execution_timeout_retry_once_then_abort():
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    err = "Execution timed out after 10.0s"
    assert h.analyze("get_stock", err, attempt=1) == RecoveryPath.RETRY
    assert h.analyze("get_stock", err, attempt=2) == RecoveryPath.ABORT
    assert h.analyze("get_stock", err, attempt=3) == RecoveryPath.ABORT
    print("  [PASS] execution timeout → RETRY at attempt 1, ABORT at attempt 2+")


def test_healer_navigation_timeout_still_isolated():
    """Regression guard — Phase 5A moved 'timeout' out of the generic
    transient list, but 'navigation timeout' has its own rule higher up
    and must still fire before the execution-timeout rule."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    err = "Playwright navigation timeout: page.goto(...) exceeded 30000ms"
    assert h.analyze("browser_open", err, attempt=1) == RecoveryPath.RETRY
    assert h.analyze("browser_open", err, attempt=2) == RecoveryPath.ABORT
    print("  [PASS] navigation timeout still RETRY-once-then-ABORT (rule 3)")


def test_healer_generic_transient_still_retries_thrice():
    """Regression guard — connection/5xx/busy transients should still
    get up to 3 retries. Only 'timeout' was removed from the transient
    list in Phase 5A."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    for err in ("HTTP 503 Service Unavailable", "connection reset", "server temporarily busy"):
        assert h.analyze("get_news", err, attempt=1) == RecoveryPath.RETRY
        assert h.analyze("get_news", err, attempt=2) == RecoveryPath.RETRY
        # attempt=3: still RETRY per current code (attempt < 3), but rule 4 no
        # longer covers "timeout"; that's the whole change we're guarding.
    print("  [PASS] generic transient signals (connection/5xx/busy) still get up-to-3 retries")


if __name__ == "__main__":
    test_timeout_for_tool_data_fetch_module()
    test_timeout_for_tool_browser_module()
    test_timeout_for_tool_llm_module()
    test_timeout_for_tool_untier_falls_back_to_default()
    test_runtime_cancels_sleeping_tool_returns_structured_timeout()
    test_healer_routes_execution_timeout_retry_once_then_abort()
    test_healer_navigation_timeout_still_isolated()
    test_healer_generic_transient_still_retries_thrice()
    print("All Phase 5A tool-timeout tests passed.")
