"""Matching and title-cleaning for real-Chrome tabs.

"close youtube" did nothing: it hit the close_app rule, looked for an
application called youtube, and found none. browser_close_tab exists but
drives Playwright's own Chromium, not the Chrome the user is looking at.

The COM/UIA calls are not exercised here — they need a real Chrome window and
a real desktop session. What IS pinned is every decision made about the
strings those calls return, because that is where a wrong tab gets closed.
Real titles below are copied verbatim from the user's actual window.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core import chrome_tabs

# Verbatim from a live Chrome window.
REAL_TITLES = [
    "localhost - Network error",
    "ChatGPT - sg_cube_v2 - Memory usage - 456 MB",
    "dulo.gd — Stream Movies & TV Shows (formerly Dulo TV) - Inactive tab - 232 MB freed up",
    "Your Repositories - Memory usage - 195 MB",
    "New Tab",
    "SG Cube — Your AI Assistant",
    "polama cloud - Google Search",
    "ONYX | Development Pipeline",
    "(2) YouTube",
    "(2) LLM Full Course For Data Engineers (From SCRATCH) - YouTube",
]


# ── title cleaning ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, clean", [
    ("(2) YouTube", "(2) YouTube"),
    ("ChatGPT - sg_cube_v2 - Memory usage - 456 MB", "ChatGPT - sg_cube_v2"),
    ("localhost - Network error", "localhost"),
    ("Your Repositories - Memory usage - 195 MB", "Your Repositories"),
])
def test_chrome_status_decorations_are_stripped(raw, clean):
    """Memory-saver and network suffixes are Chrome's status text, not the
    page title. Reading them back aloud would be nonsense."""
    assert chrome_tabs.clean_title(raw) == clean


def test_a_dash_inside_a_real_title_survives():
    """The cleaner must cut Chrome's suffixes, not every dash — "ChatGPT -
    sg_cube_v2" keeps its own."""
    assert "sg_cube_v2" in chrome_tabs.clean_title(
        "ChatGPT - sg_cube_v2 - Memory usage - 456 MB")


# ── matching ─────────────────────────────────────────────────────────────

def test_youtube_matches_both_youtube_tabs():
    """The reported case. Two tabs, and "close youtube" means both."""
    hits = [t for t in REAL_TITLES if chrome_tabs.matches("youtube", t)]
    assert hits == [
        "(2) YouTube",
        "(2) LLM Full Course For Data Engineers (From SCRATCH) - YouTube",
    ]


def test_matching_is_case_insensitive():
    for q in ("YouTube", "YOUTUBE", "youtube"):
        assert chrome_tabs.matches(q, "(2) YouTube"), q


def test_matching_sees_through_the_status_suffix():
    """A memory-saved tab must still be closable — matching the RAW name
    would miss "YouTube - Inactive tab - 232 MB freed up"."""
    assert chrome_tabs.matches("dulo", REAL_TITLES[2])


def test_an_unrelated_query_matches_nothing():
    """The failure that costs the user work: a query that means no open tab
    must close none of them."""
    for q in ("spotify", "netflix", "figma"):
        assert not any(chrome_tabs.matches(q, t) for t in REAL_TITLES), q


def test_an_empty_query_matches_nothing():
    """An empty target must never mean "everything" — a mis-heard command
    would close the entire window."""
    for q in ("", "   ", None):
        assert not any(chrome_tabs.matches(q, t) for t in REAL_TITLES)


def test_a_query_can_match_a_page_title_not_just_a_domain():
    assert chrome_tabs.matches("development pipeline", "ONYX | Development Pipeline")


# ── platform guard ───────────────────────────────────────────────────────

def test_everything_degrades_quietly_when_uia_is_unavailable(monkeypatch):
    """Off Windows, or with the dependency missing, tab tools must return
    empty rather than raising into the middle of a turn."""
    monkeypatch.setattr(chrome_tabs, "available", lambda: False)
    assert chrome_tabs.list_tabs() == []
    assert chrome_tabs.close_matching("youtube") == []
