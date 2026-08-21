"""A tool's own network timeout must fire INSIDE its execution budget.

Seen live:

    Task get_news (ec5fa387) timed out after 10.0s
    [ai] The provided search results do not contain specific latest
         technology news.  (latency: 36081ms, tools: 3)

_FEED_TIMEOUT_S was 8.0 inside a 10.0s data-fetch budget — 2s of headroom for
DNS, TLS, redirects, feed parsing and thread-pool scheduling. A merely slow
feed therefore overran the OUTER asyncio.wait_for instead of failing inside
the tool, which costs twice:

  * the user gets "timed out" instead of the tool's own error, which the
    planner can relay and reason about
  * tools run in a thread pool, so wait_for cancels the AWAIT while the
    blocking fetch keeps running — the leaked worker that fetch_feed's own
    docstring was written to prevent

The fix is the ratio, not the number, so this pins the ratio. Adding a new
data-fetch tool, or trimming the tier budget in config, must not silently
recreate the overrun.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.tools import data_sources
from backend.server.config import settings

# Seconds that must remain after the network has given up, for feedparser and
# thread-pool scheduling.
_MIN_HEADROOM_S = 2.5


def test_worst_case_feed_timeout_fits_inside_the_data_fetch_budget():
    budget = settings.tool_timeout_data_fetch_s
    worst = data_sources._FEED_TIMEOUT_S
    assert worst + _MIN_HEADROOM_S <= budget, (
        f"worst-case feed timeout {worst}s against a {budget}s tool budget "
        f"leaves only {budget - worst}s for parsing and scheduling; a slow "
        f"feed will be killed by the outer wait_for and leak its worker thread"
    )


def test_the_worst_case_is_the_sum_of_the_phases():
    """The whole defect was assuming a bare float bounds the request. httpx
    applies it to connect, read, write and pool INDEPENDENTLY, so the real
    ceiling is their sum — a 5.0 float measured 10.15s against a slow host.
    If someone collapses these back into one number, this fails."""
    assert data_sources._FEED_TIMEOUT_S == (
        data_sources._FEED_CONNECT_S + data_sources._FEED_READ_S
        + data_sources._FEED_WRITE_S + data_sources._FEED_POOL_S)


def test_fetch_feed_builds_a_per_phase_timeout():
    """A bare float reaching httpx.Client is the bug returning."""
    t = data_sources._feed_timeout()
    assert t.connect == data_sources._FEED_CONNECT_S
    assert t.read == data_sources._FEED_READ_S


def test_a_smaller_caller_budget_scales_every_phase():
    """Callers pass a total; it must not be applied four times over."""
    t = data_sources._feed_timeout(data_sources._FEED_TIMEOUT_S / 2)
    total = t.connect + t.read + t.write + t.pool
    assert total == pytest.approx(data_sources._FEED_TIMEOUT_S / 2)


def test_the_budget_itself_is_still_sane():
    """If the tier budget were raised to hide the problem, the ratio above
    would pass while every news query got slower. Bound it."""
    assert 5.0 <= settings.tool_timeout_data_fetch_s <= 20.0


def test_news_and_feed_tools_are_in_the_data_fetch_tier():
    """The ratio only protects modules that actually resolve to this budget.
    If `news` drifted out of the tier, this file would guard nothing."""
    from backend.core.tools import registry
    assert "news" in registry._DATA_FETCH_MODULES
    assert "data_sources" in registry._DATA_FETCH_MODULES
