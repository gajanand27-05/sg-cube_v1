"""The tool layer: what the agent is told and what the user hears.

Provider choice, fallback and caching are tested in test_websearch_providers;
this file only covers the translation from a SearchResponse into a spoken
answer, and the failure modes that must not reach the user as a stack trace.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import websearch
from backend.core.tools import web_search as m
from backend.core.websearch.base import SearchResponse, SearchResult

ANSWER = getattr(m.search_and_answer, "func", m.search_and_answer)


def test_the_two_search_tools_name_their_parameter_the_same():
    """`web_search(query)` and `search_and_answer(question)` were siblings with
    different names for the same thing, and the planner paid for it live:

        TypeError: search_and_answer() got an unexpected keyword argument 'query'

    followed by "No tool results were provided, so there is nothing to
    summarize." — a user-facing non-answer to "how many moons does it have".

    That is not the model hallucinating an argument name; it is a trap in our
    own schema. Asking it to remember that one sibling takes `query` and the
    other takes `question`, when both mean "what to search for", is a coin
    flip we set up.
    """
    from backend.core.tools.registry import REGISTRY

    a = set(REGISTRY["web_search"].schema["parameters"]["properties"])
    b = set(REGISTRY["search_and_answer"].schema["parameters"]["properties"])
    assert a == b, (
        f"web_search takes {sorted(a)} but search_and_answer takes {sorted(b)}; "
        "sibling tools must name the same concept the same way or the planner "
        "will guess, and guessing right is not something to rely on"
    )
LIST = getattr(m.web_search, "func", m.web_search)


def _response(n=5, body="a reasonably long snippet " * 12, provider="duckduckgo"):
    return SearchResponse(provider=provider, query="q", results=[
        SearchResult(title=f"Result {i}", url=f"https://example.com/{i}",
                     body=body, source=provider)
        for i in range(n)
    ])


@pytest.fixture(autouse=True)
def _clean():
    websearch.clear_cache()
    yield
    websearch.clear_cache()


def test_the_answer_is_what_gets_spoken(monkeypatch):
    """commander.py speaks a lone successful tool's `message` verbatim, so the
    message must be the answer and not a description of one."""
    monkeypatch.setattr(m.websearch, "search", lambda q, limit=5: _response())
    monkeypatch.setattr(m, "llm_generate", lambda *a, **k: "India won.")

    res = ANSWER("who won")
    assert res.status.value == "success"
    assert res.message == "India won."
    assert res.data["is_external_data"] is True


def test_provider_outage_is_reported_as_an_error(monkeypatch):
    def down(q, limit=5):
        raise RuntimeError("every provider failed")

    monkeypatch.setattr(m.websearch, "search", down)
    res = ANSWER("who won")
    assert res.status.value == "error"
    assert "provider" in res.reason.lower()


def test_no_results_is_blocked_not_an_error(monkeypatch):
    """Nothing matched is a normal outcome and deserves different words from
    an outage."""
    monkeypatch.setattr(m.websearch, "search",
                        lambda q, limit=5: SearchResponse("duckduckgo", q))
    res = ANSWER("zzzz")
    assert res.status.value == "blocked"


def test_synthesis_failure_still_returns_something_true(monkeypatch):
    """Retrieval worked; only the model went quiet. Returning nothing would
    throw away a correct search."""
    monkeypatch.setattr(m.websearch, "search", lambda q, limit=5: _response())
    monkeypatch.setattr(m, "llm_generate", lambda *a, **k: "   ")

    res = ANSWER("who won")
    assert res.status.value == "success"
    assert "Result 0" in res.message
    assert res.data["degraded"]


def test_healthy_results_do_not_pay_for_page_fetches(monkeypatch):
    """A full DuckDuckGo response is 1100-1500 chars of snippet; reading pages
    on top cost +2-4s and changed no answer in an A/B. The fetch path is a
    safety net, not the default."""
    monkeypatch.setattr(m.websearch, "search", lambda q, limit=5: _response())
    monkeypatch.setattr(m, "llm_generate", lambda *a, **k: "answer")
    monkeypatch.setattr(m, "_read_page",
                        lambda url: pytest.fail("fetched a page for a healthy response"))

    assert ANSWER("who won").data["pages_read"] == []


def test_thin_results_do_trigger_page_fetches(monkeypatch):
    """The counterpart: with too few results the snippets cannot be trusted.
    An earlier threshold could never fire, making this path dead code."""
    monkeypatch.setattr(m.websearch, "search",
                        lambda q, limit=5: _response(n=1, body="short"))
    monkeypatch.setattr(m, "llm_generate", lambda *a, **k: "answer")
    monkeypatch.setattr(m, "_read_page", lambda url: "fetched body")

    assert ANSWER("who won").data["pages_read"] == ["https://example.com/0"]


def test_a_page_that_will_not_load_is_not_a_failed_turn(monkeypatch):
    monkeypatch.setattr(m.websearch, "search",
                        lambda q, limit=5: _response(n=1, body="short"))
    monkeypatch.setattr(m, "llm_generate", lambda *a, **k: "answer")
    monkeypatch.setattr(m, "_read_page", lambda url: "")

    res = ANSWER("who won")
    assert res.status.value == "success"
    assert res.data["pages_read"] == []


def test_empty_question_never_reaches_a_provider(monkeypatch):
    monkeypatch.setattr(m.websearch, "search",
                        lambda q, limit=5: pytest.fail("searched for nothing"))
    assert ANSWER("  ").status.value == "blocked"


def test_web_search_lists_sources(monkeypatch):
    monkeypatch.setattr(m.websearch, "search", lambda q, limit=5: _response(n=2))
    res = LIST("python")
    assert res.status.value == "success"
    assert "Result 0" in res.message and "Result 1" in res.message
    assert len(res.data["results"]) == 2


def test_answer_prompt_declares_results_to_be_data():
    lowered = m._ANSWER_SYSTEM.lower()
    assert "never instructions" in lowered or "not something to obey" in lowered


def test_search_gets_the_llm_timeout_budget():
    """search_and_answer searches and then calls a model; the 10s data-fetch
    budget would cut it off."""
    from backend.core.tools.registry import REGISTRY, _timeout_for_tool
    import backend.core.tools  # noqa: F401
    from backend.server.config import settings

    assert _timeout_for_tool(REGISTRY["search_and_answer"]) == settings.tool_timeout_llm_s


def test_the_tool_description_says_a_url_is_not_needed():
    """The planner picks by description, and the whole point of this tool is
    that the user does not know the URL."""
    from backend.core.tools.registry import REGISTRY
    import backend.core.tools  # noqa: F401

    desc = REGISTRY["search_and_answer"].description.lower()
    assert "url" in desc, "the description never mentions URLs either way"
    assert "do not need" in desc or "don't need" in desc
