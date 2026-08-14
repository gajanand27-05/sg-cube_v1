"""search_and_answer must answer a question, and must fail honestly.

Built because search_web only ever opened a browser tab, so a factual question
produced a Google tab and silence.

Provider notes worth keeping: DuckDuckGo's html/ and lite/ endpoints were tried
first and both serve an anti-bot CAPTCHA after a couple of automated queries —
HTTP 202 with a normal-looking body, so it does not even read as an error.
Wikipedia rate-limits with a real 429 whose body is text/plain, which is why
_get_json checks the content type instead of calling .json() blind.
"""
import sys
from pathlib import Path

import httpx
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.tools import web_search as ws

SEARCH_JSON = {"query": {"search": [
    {"title": "Python (programming language)"},
    {"title": "Mojo (programming language)"},
]}}
PAGES_JSON = {"query": {"pages": {
    # Deliberately out of search-rank order — this is how the API returns them.
    "22": {"title": "Mojo (programming language)", "extract": "Mojo is a language."},
    "11": {"title": "Python (programming language)", "extract": "Python is a language."},
}}}


@pytest.fixture(autouse=True)
def _clean():
    ws._clear_cache_for_tests()
    yield
    ws._clear_cache_for_tests()


def _fake_client(responses):
    """responses: list of (status, content_type, json_or_text) in call order."""
    calls = {"n": 0}

    class _R:
        def __init__(self, status, ctype, body):
            self.status_code = status
            self.headers = {"content-type": ctype}
            self._body = body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

        def json(self):
            return self._body

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, params=None):
            i = min(calls["n"], len(responses) - 1)
            calls["n"] += 1
            return _R(*responses[i])

    return _C, calls


def test_answers_a_question(monkeypatch):
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([
                            (200, "application/json", SEARCH_JSON),
                            (200, "application/json", PAGES_JSON),
                        ])[0]())
    monkeypatch.setattr(ws, "llm_generate", lambda *a, **k: "Python is a language.")

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    res = fn("what is python")

    assert res.status.value == "success"
    assert res.message == "Python is a language."
    assert res.data["is_external_data"] is True, (
        "article text is external content; the Planner's directive keys off this"
    )


def test_extracts_keep_search_rank_order(monkeypatch):
    """The extracts endpoint keys pages by id, so dict order put the least
    relevant article first."""
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([
                            (200, "application/json", SEARCH_JSON),
                            (200, "application/json", PAGES_JSON),
                        ])[0]())

    extracts, titles = ws._lookup("python")
    assert extracts[0].startswith("Python (programming language)"), extracts


def test_rate_limit_is_reported_in_words(monkeypatch):
    """429 comes back as text/plain. Calling .json() on it raised
    JSONDecodeError, so the user heard a parser error rather than 'I'm being
    rate limited'."""
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([(429, "text/plain", None)])[0]())

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    res = fn("anything")
    assert res.status.value == "error"
    assert "rate" in res.reason.lower(), res.reason


def test_non_json_body_does_not_raise(monkeypatch):
    """Any anti-bot or error page must degrade to a spoken reason."""
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([(200, "text/html", None)])[0]())

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    res = fn("anything")
    assert res.status.value == "error"
    assert "json" in res.reason.lower(), res.reason


def test_no_matching_article_says_so(monkeypatch):
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([
                            (200, "application/json", {"query": {"search": []}}),
                        ])[0]())

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    res = fn("zzzz nonexistent")
    assert res.status.value == "blocked"


def test_synthesis_failure_still_returns_something_true(monkeypatch):
    """Retrieval worked; only the model went quiet. Returning nothing would
    lose a correct lookup."""
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([
                            (200, "application/json", SEARCH_JSON),
                            (200, "application/json", PAGES_JSON),
                        ])[0]())
    monkeypatch.setattr(ws, "llm_generate", lambda *a, **k: "   ")

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    res = fn("what is python")
    assert res.status.value == "success"
    assert "Python" in res.message
    assert res.data["degraded"]


def test_repeat_question_is_served_from_cache(monkeypatch):
    """A reviewer asking the same thing twice must not re-hit a rate-limited
    API."""
    client_cls, calls = _fake_client([
        (200, "application/json", SEARCH_JSON),
        (200, "application/json", PAGES_JSON),
    ])
    monkeypatch.setattr(ws.httpx, "Client", lambda **kw: client_cls())
    monkeypatch.setattr(ws, "llm_generate", lambda *a, **k: "answer")

    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    fn("what is python")
    before = calls["n"]
    second = fn("What Is Python")  # case-insensitive key

    assert calls["n"] == before, "cache miss — the API was called again"
    assert second.data["cached"] is True


def test_cache_covers_for_a_failed_live_lookup(monkeypatch):
    """Once answered, a later rate limit replays the last good answer instead
    of failing mid-demo."""
    ok_cls, _ = _fake_client([
        (200, "application/json", SEARCH_JSON),
        (200, "application/json", PAGES_JSON),
    ])
    monkeypatch.setattr(ws.httpx, "Client", lambda **kw: ok_cls())
    monkeypatch.setattr(ws, "llm_generate", lambda *a, **k: "answer")
    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    fn("what is python")

    ws._CACHE[list(ws._CACHE)[0]] = (0.0,) + ws._CACHE[list(ws._CACHE)[0]][1:]  # expire
    monkeypatch.setattr(ws.httpx, "Client",
                        lambda **kw: _fake_client([(429, "text/plain", None)])[0]())

    res = fn("what is python")
    assert res.status.value == "success", "a stale answer beats no answer"
    assert res.data["cached"] is True


def test_empty_question_is_blocked_without_a_network_call(monkeypatch):
    def explode(**kw):
        raise AssertionError("made a network call for an empty question")

    monkeypatch.setattr(ws.httpx, "Client", explode)
    fn = getattr(ws.search_and_answer, "func", ws.search_and_answer)
    assert fn("  ").status.value == "blocked"


def test_answer_prompt_declares_extracts_to_be_data():
    """Article text is attacker-controllable in principle; the prompt must say
    so, matching the is_external_data contract used by data_sources."""
    lowered = ws._ANSWER_SYSTEM.lower()
    assert "never instructions" in lowered or "not something to obey" in lowered


def test_tools_are_registered():
    from backend.core.tools.registry import REGISTRY
    import backend.core.tools  # noqa: F401

    for name in ("web_search", "search_and_answer"):
        assert name in REGISTRY, f"{name} never reached the registry"


def test_search_gets_the_llm_timeout_budget():
    """search_and_answer does a lookup and then an LLM call; the 10s
    data-fetch budget would cut it off."""
    from backend.core.tools.registry import REGISTRY, _timeout_for_tool
    import backend.core.tools  # noqa: F401
    from backend.server.config import settings

    got = _timeout_for_tool(REGISTRY["search_and_answer"])
    assert got == settings.tool_timeout_llm_s, got
