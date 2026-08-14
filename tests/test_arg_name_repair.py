"""Hallucinated argument names must not cost a round trip.

_coerce_args maps unknown arg keys onto schema params by substring
containment ("app_name" -> "name"). That can't relate get_news_data(query=...)
to its `topic` param — the words share no letters — so the call raised
TypeError, the agent saw the error, re-read the schema and called again.
Measured on the live assistant: an extra ~7s on "what is the latest news about
artificial intelligence".
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import backend.core.tools as _load_all_tools  # noqa: F401  (populates REGISTRY)
from backend.core.tools.registry import REGISTRY, _coerce_args


def test_substring_match_still_wins():
    """The original behaviour, kept: 'app_name' -> 'name'."""
    assert _coerce_args("open_app", {"app_name": "notepad"}) == {"name": "notepad"}


def test_unrelated_arg_name_binds_positionally():
    """The regression: query/topic share no substring."""
    assert _coerce_args("get_news_data", {"query": "artificial intelligence"}) == {
        "topic": "artificial intelligence"
    }


def test_a_correct_call_is_left_alone():
    args = {"topic": "tech", "limit": 3}
    assert _coerce_args("get_news_data", args) == args


def test_positional_bind_respects_the_declared_type():
    """An int can't fill a string slot just because it was the only spare
    parameter. Better to raise than to silently answer the wrong question."""
    out = _coerce_args("get_news_data", {"count": 3})
    assert out == {"count": 3}, f"bound a number into a string param: {out}"


def test_two_unknown_args_stay_unbound():
    """One unplaced argument has a single reading; two do not."""
    out = _coerce_args("get_news_data", {"query": "ai", "howmany": 3})
    assert out == {"query": "ai", "howmany": 3}


def test_partial_call_binds_only_the_stray_arg():
    """`limit` is already correct; only `query` needs rehoming."""
    assert _coerce_args("get_news_data", {"query": "tech", "limit": 2}) == {
        "topic": "tech", "limit": 2,
    }


@pytest.mark.parametrize("tool_name,bad,expected", [
    ("get_stock", {"ticker": "AAPL"}, {"symbol": "AAPL"}),
    ("read_webpage", {"link": "https://x.com"}, {"url": "https://x.com"}),
    ("summarize_url", {"page": "https://x.com"}, {"url": "https://x.com"}),
])
def test_common_aliases_across_tools(tool_name, bad, expected):
    if tool_name not in REGISTRY:
        pytest.skip(f"{tool_name} not registered")
    assert _coerce_args(tool_name, bad) == expected


def test_repair_never_invents_a_value():
    """Empty in, empty out — a repair pass must not fabricate arguments."""
    assert _coerce_args("get_news_data", {}) == {}
