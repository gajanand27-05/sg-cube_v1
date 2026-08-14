"""The Wikipedia fallback provider.

Kept as a provider rather than dropped when DuckDuckGo became the primary,
because it fails independently — different host, different infrastructure,
different throttling — so it can still answer when the search engine cannot.
"""
import sys
from pathlib import Path

import httpx
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.websearch import wikipedia as w

SEARCH_JSON = {"query": {"search": [
    {"title": "Python (programming language)"},
    {"title": "Mojo (programming language)"},
]}}
PAGES_JSON = {"query": {"pages": {
    # Deliberately out of search-rank order — this is how the API returns them.
    "22": {"title": "Mojo (programming language)", "extract": "Mojo is a language."},
    "11": {"title": "Python (programming language)", "extract": "Python is a language."},
}}}


def _client(responses):
    class _R:
        def __init__(self, status, ctype, body):
            self.status_code, self._body = status, body
            self.headers = {"content-type": ctype}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

        def json(self):
            return self._body

    class _C:
        n = 0

        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, params=None):
            i = min(_C.n, len(responses) - 1)
            _C.n += 1
            return _R(*responses[i])

    _C.n = 0
    return _C


def test_results_keep_search_rank_order(monkeypatch):
    """The extracts endpoint keys pages by id, so dict order put 'Mojo' ahead
    of 'Python' for a question about Python."""
    monkeypatch.setattr(w.httpx, "Client", lambda **kw: _client([
        (200, "application/json", SEARCH_JSON),
        (200, "application/json", PAGES_JSON),
    ])())

    results = w.WikipediaProvider().search("python", 2)
    assert [r.title for r in results] == [
        "Python (programming language)", "Mojo (programming language)"]


def test_rate_limit_is_reported_in_words(monkeypatch):
    """429 comes back as text/plain. Calling .json() on it raised
    JSONDecodeError, so the failure surfaced as a parser error."""
    monkeypatch.setattr(w.httpx, "Client",
                        lambda **kw: _client([(429, "text/plain", None)])())

    with pytest.raises(RuntimeError, match="rate-limit"):
        w.WikipediaProvider().search("q", 3)


def test_non_json_body_raises_a_readable_error(monkeypatch):
    monkeypatch.setattr(w.httpx, "Client",
                        lambda **kw: _client([(200, "text/html", None)])())

    with pytest.raises(RuntimeError, match="not JSON"):
        w.WikipediaProvider().search("q", 3)


def test_no_matches_is_an_empty_list_not_an_exception(monkeypatch):
    """The chain distinguishes 'nothing matched' from 'this provider is down';
    raising here would wrongly look like an outage."""
    monkeypatch.setattr(w.httpx, "Client", lambda **kw: _client([
        (200, "application/json", {"query": {"search": []}}),
    ])())

    assert w.WikipediaProvider().search("zzzz", 3) == []


def test_results_carry_a_usable_url(monkeypatch):
    monkeypatch.setattr(w.httpx, "Client", lambda **kw: _client([
        (200, "application/json", SEARCH_JSON),
        (200, "application/json", PAGES_JSON),
    ])())

    first = w.WikipediaProvider().search("python", 2)[0]
    assert first.url == "https://en.wikipedia.org/wiki/Python_(programming_language)"
    assert first.source == "wikipedia"


def test_user_agent_identifies_the_software():
    """Wikimedia's API policy asks for this; a generic browser UA is what gets
    anonymous traffic throttled."""
    assert "SG_CUBE" in w._HEADERS["User-Agent"]
