""""close youtube" should close the YouTube tab, not report failure.

YouTube is not an application. The close_app rule fires on "close X" for any
X, handle_close_app looks for a matching PROCESS, finds none, and returns
"'youtube' is not running" — which is true and useless, because the thing the
user is looking at is a Chrome tab.

So close_app falls back to the real Chrome tab strip when, and only when, no
process matched. The ordering matters in both directions:

  * a running app must still be closed as an app — "close chrome" means the
    browser, not a tab that happens to mention chrome
  * a blocked-for-any-other-reason target (dangerous, empty) must NOT reach
    the fallback, or the safety check becomes a suggestion
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core import chrome_tabs
from backend.core.tools import builtins


@pytest.fixture
def no_process(monkeypatch):
    """Nothing is running, so every close_app lands on the fallback."""
    monkeypatch.setattr(
        builtins.cw, "handle_close_app",
        lambda intent: {"status": "blocked",
                        "reason": f"{intent.target!r} is not running"})


def test_close_youtube_closes_the_tab(no_process, monkeypatch):
    monkeypatch.setattr(chrome_tabs, "available", lambda: True)
    monkeypatch.setattr(chrome_tabs, "close_matching",
                        lambda q: ["(2) YouTube"])

    res = builtins.close_app("youtube")
    assert res.status == "success"
    assert "YouTube" in res.message


def test_it_names_every_tab_it_closed(no_process, monkeypatch):
    """Matching is loose, so the titles are the user's only way to notice it
    took something they wanted."""
    monkeypatch.setattr(chrome_tabs, "available", lambda: True)
    monkeypatch.setattr(chrome_tabs, "close_matching", lambda q: [
        "(2) YouTube",
        "(2) LLM Full Course For Data Engineers (From SCRATCH) - YouTube",
    ])
    res = builtins.close_app("youtube")
    assert "LLM Full Course" in res.message and "(2) YouTube" in res.message


def test_a_running_app_is_still_closed_as_an_app(monkeypatch):
    """"close chrome" must kill the browser, not hunt for a tab named chrome.
    If the fallback ran first, closing an app would become unreliable."""
    called = {"tabs": False}
    monkeypatch.setattr(
        builtins.cw, "handle_close_app",
        lambda intent: {"status": "success", "message": "closed chrome"})
    monkeypatch.setattr(chrome_tabs, "close_matching",
                        lambda q: called.__setitem__("tabs", True) or [])

    res = builtins.close_app("chrome")
    assert res.status == "success"
    assert called["tabs"] is False, "the tab fallback ran for a running app"


def test_a_dangerous_target_never_reaches_the_fallback(monkeypatch):
    """The safety check must not be routed around. Anything blocked for a
    reason OTHER than "not running" stops here."""
    called = {"tabs": False}
    monkeypatch.setattr(
        builtins.cw, "handle_close_app",
        lambda intent: {"status": "blocked",
                        "reason": "dangerous target rejected: 'explorer.exe'"})
    monkeypatch.setattr(chrome_tabs, "close_matching",
                        lambda q: called.__setitem__("tabs", True) or [])

    res = builtins.close_app("explorer.exe")
    assert res.status == "blocked"
    assert called["tabs"] is False, "a dangerous target reached the fallback"


def test_no_matching_tab_reports_the_original_problem(no_process, monkeypatch):
    """When neither an app nor a tab matches, the user should hear that
    nothing matched — not a fallback error about Chrome."""
    monkeypatch.setattr(chrome_tabs, "available", lambda: True)
    monkeypatch.setattr(chrome_tabs, "close_matching", lambda q: [])

    res = builtins.close_app("spotify")
    assert res.status == "blocked"
    assert "spotify" in res.reason.lower()


def test_the_fallback_is_skipped_when_uia_is_unavailable(no_process, monkeypatch):
    """Off Windows this must behave exactly as it did before."""
    monkeypatch.setattr(chrome_tabs, "available", lambda: False)
    res = builtins.close_app("youtube")
    assert res.status == "blocked"
    assert "not running" in res.reason
