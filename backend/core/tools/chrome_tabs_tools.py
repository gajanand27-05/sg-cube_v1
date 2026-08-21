"""Tools for the user's REAL Chrome tabs.

Distinct from the browser_* tools, which drive Playwright's own Chromium — a
separate browser the user never sees. These read and close tabs in the Chrome
window actually on screen.
"""
from backend.core import chrome_tabs
from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool

_UNAVAILABLE = (
    "cannot read Chrome tabs on this system (needs Windows UI Automation)")


@tool(tier=CapabilityTier.READONLY)  # tier: reads window titles, no side effects
def list_chrome_tabs() -> ToolResult:
    """List the tabs open in the user's real Chrome window, by title. Use for
    "what tabs do I have open" or to check before closing one. This is the
    Chrome the user is looking at — NOT the browser_* tools, which drive a
    separate automation browser."""
    if not chrome_tabs.available():
        return ToolResult.blocked(_UNAVAILABLE)
    tabs = chrome_tabs.list_tabs()
    if not tabs:
        return ToolResult.success("No Chrome window is open.")
    listing = "; ".join(t.title for t in tabs)
    return ToolResult.success(f"{len(tabs)} tab(s) open: {listing}")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.SYSTEM_WRITE)  # tier: reversible with Ctrl+Shift+T
def close_chrome_tab(name: str) -> ToolResult:
    """Close tabs in the user's real Chrome whose title contains `name`.
    Use for "close youtube", "close the gmail tab". Closes EVERY matching tab
    and reports which ones. Matching is loose on purpose, so always tell the
    user the titles that were closed."""
    if not chrome_tabs.available():
        return ToolResult.blocked(_UNAVAILABLE)
    if not (name or "").strip():
        # An empty target would match every tab and close the whole window.
        return ToolResult.blocked("no tab name given")

    closed = chrome_tabs.close_matching(name)
    if not closed:
        open_now = [t.title for t in chrome_tabs.list_tabs()]
        if not open_now:
            return ToolResult.blocked("No Chrome window is open.")
        return ToolResult.blocked(
            f"no open tab matches {name!r}. Open tabs: {'; '.join(open_now)}")

    # Name what went, always. The match is deliberately loose, so this is the
    # user's only way to notice it took something they wanted.
    if len(closed) == 1:
        return ToolResult.success(f"Closed tab: {closed[0]}")
    return ToolResult.success(
        f"Closed {len(closed)} tabs: {'; '.join(closed)}")
