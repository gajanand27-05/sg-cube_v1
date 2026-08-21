"""Read and close tabs in the user's REAL Chrome.

`browser_close_tab` looks like it already does this and does not: the browser
tools drive Playwright's own Chromium, launched via
launch_persistent_context(user_data_dir=...). That is a separate browser the
user never looks at. "close youtube" hit the close_app rule instead, went
looking for an application called youtube, found none, and did nothing.

Chrome publishes its tab strip over UI Automation, so the real window can be
read without CDP (which would need Chrome restarted with a debugging port)
and without keyboard cycling (which steals focus and sends Ctrl+W wherever it
happens to land — a mis-timed one closes the wrong window entirely).

Windows-only by nature. Every entry point degrades to an empty list or a
blocked result off Windows rather than raising, so a turn that mentions tabs
on another platform fails politely instead of crashing.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Chrome appends this to every window title; it is not part of any tab name.
_CHROME_SUFFIX = " - Google Chrome"

# UIA's own noise, appended to tab names by Chrome's memory saver. "YouTube -
# Inactive tab - 232 MB freed up" must still match a search for "youtube",
# and must not be read back to the user as if it were the page title.
_TAB_NOISE = (
    " - Inactive tab", " - Memory usage", " - Network error",
    " - Audio playing", " - Audio muted",
)


@dataclass(frozen=True)
class Tab:
    title: str
    index: int


def available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import uiautomation  # noqa: F401
        return True
    except Exception:
        return False


def clean_title(raw: str) -> str:
    """Strip Chrome's status decorations from a tab name."""
    title = (raw or "").strip()
    for noise in _TAB_NOISE:
        cut = title.find(noise)
        if cut > 0:
            title = title[:cut]
    return title.strip()


def matches(query: str, title: str) -> bool:
    """Does `title` name the thing the user asked to close?

    Substring, case-insensitive, on the cleaned title. Deliberately loose:
    people say "youtube" for a tab called
    "(2) LLM Full Course For Data Engineers - YouTube". The caller is
    responsible for reporting exactly what it closed, which is what keeps a
    loose match honest.
    """
    q = (query or "").strip().lower()
    if not q:
        return False
    return q in clean_title(title).lower()


def _configure_uia(auto) -> None:
    """Stop uiautomation writing @AutomationLog.txt into the working
    directory. It logs control-lookup failures to a file next to wherever the
    process happened to start — which for this app is the repo root. Its
    failures are already surfaced through log.warning here."""
    try:
        auto.Logger.WriteFlag = False
    except Exception:
        pass


def _chrome_windows():
    import uiautomation as auto

    _configure_uia(auto)
    auto.SetGlobalSearchTimeout(2)
    for win in auto.GetRootControl().GetChildren():
        if win.ClassName == "Chrome_WidgetWin_1" and (win.Name or "").endswith(
                _CHROME_SUFFIX):
            yield win


def _tab_items(win):
    tabs = win.TabControl(searchDepth=8)
    if not tabs.Exists(1):
        return []
    return [t for t in tabs.GetChildren()
            if t.ControlTypeName == "TabItemControl"]


def list_tabs() -> list[Tab]:
    """Every open tab across every Chrome window, in strip order."""
    if not available():
        return []
    out: list[Tab] = []
    try:
        for win in _chrome_windows():
            for item in _tab_items(win):
                title = clean_title(item.Name)
                if title:
                    out.append(Tab(title=title, index=len(out)))
    except Exception as e:  # UIA is COM; treat any failure as "no tabs"
        log.warning("could not read Chrome tabs: %s", e)
        return []
    return out


def close_matching(query: str) -> list[str]:
    """Close every tab whose title matches, returning the titles closed.

    Closes ALL matches rather than picking one. "close youtube" with two
    YouTube tabs open means both — choosing one would be a coin flip, and
    unlike a message to the wrong person this is recoverable with
    Ctrl+Shift+T. The caller reports the titles so the user always hears what
    went.

    Selects the tab and sends Ctrl+W rather than clicking the tab's own X.
    Chrome gives a background tab's close button a (0,0,0,0) bounding
    rectangle — the button exists in the tree but cannot be clicked, so the
    click silently does nothing. Measured: it reported closing "New Tab" while
    all 13 tabs stayed open.

    The return value is computed by DIFFING the tab list before and after, not
    by counting attempts. An unverified list here would make the assistant say
    "Closed the YouTube tab" over a window where nothing moved, which is the
    same confident-but-false failure as answering "Done." having run no tools.

    Iterates a snapshot in reverse: closing a tab reindexes the strip, so
    walking forward over a live collection skips the tab after each close.
    """
    if not available():
        return []
    import uiautomation as auto

    before = [t.title for t in list_tabs()]
    if not any(matches(query, t) for t in before):
        return []

    try:
        for win in _chrome_windows():
            targets = [item for item in reversed(_tab_items(win))
                       if matches(query, clean_title(item.Name))]
            if not targets:
                continue
            win.SetActive()
            for item in targets:
                # Select the tab, then close the ACTIVE one. Ctrl+W goes to
                # whatever is focused, so the window is activated first and
                # the key is sent through the tab item itself.
                item.Click(simulateMove=False, waitTime=0.05)
                auto.SendKeys("{Ctrl}w", waitTime=0.15)
    except Exception as e:
        log.warning("could not close Chrome tabs: %s", e)

    after = [t.title for t in list_tabs()]
    remaining = list(after)
    closed: list[str] = []
    for title in before:
        if title in remaining:
            remaining.remove(title)
        else:
            closed.append(title)
    return closed
