"""'search the web for X' must search for X, not for 'the web for X'.

The catch-all rule `^search (?:for )?(?P<query>.+)$` swallowed the carrier
phrase, so asking the live assistant to "search the web for who won the 2024
cricket t20 world cup" opened a Google tab for the literal string "the web for
who won the 2024 cricket t20 world cup".

It also answered "Done", which sounds like a failed answer rather than a
completed action.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.orchestrator import rule_engine
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor.executor import ExecutionResult
from backend.server.routes.voice import _build_spoken_response


@pytest.mark.parametrize("said,expected", [
    ("search the web for python tutorials", "python tutorials"),
    ("search the internet for python tutorials", "python tutorials"),
    ("search online for python tutorials", "python tutorials"),
    ("search for python tutorials", "python tutorials"),
    ("google python tutorials", "python tutorials"),
    ("search the web about climate change", "climate change"),
])
def test_carrier_phrase_is_not_part_of_the_query(said, expected):
    intent = rule_engine.match(said)
    assert intent is not None, f"{said!r} matched no rule"
    assert intent.action == "search_google"
    assert intent.target == expected


def test_a_query_that_is_only_a_carrier_word_is_kept():
    """"search the web" alone must not collapse to an empty query — an empty
    search is worse than a literal one."""
    intent = rule_engine.match("search the web")
    assert intent is not None
    assert intent.target, "query collapsed to empty"


def test_youtube_still_wins_over_the_google_catch_all():
    intent = rule_engine.match("search for lofi beats on youtube")
    assert intent is not None
    assert intent.action == "search_youtube"
    assert intent.target == "lofi beats"


def _ok(action: str, target: str) -> ExecutionResult:
    return ExecutionResult(
        status="success",
        intent=Intent(action=action, target=target),
        message="ok",
        latency_ms=1,
    )


@pytest.mark.parametrize("action,target,expected_fragment", [
    ("search_google", "cricket scores", "cricket scores"),
    ("search_youtube", "lofi beats", "lofi beats"),
    ("open_url", "github.com", "github.com"),
])
def test_opening_actions_say_what_they_opened(action, target, expected_fragment):
    spoken = _build_spoken_response(
        Intent(action=action, target=target),
        _ok(action, target),
    )
    assert spoken != "Done", f"{action} still answers with a bare 'Done'"
    assert expected_fragment in spoken


def test_unmapped_success_still_falls_back_to_done():
    """The fallback must survive — a tool with no phrasing of its own should
    still say something rather than raise or go silent."""
    spoken = _build_spoken_response(
        Intent(action="some_future_action", target="x"),
        _ok("some_future_action", "x"),
    )
    assert spoken == "Done"
