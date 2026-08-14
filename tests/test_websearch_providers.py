"""The Brain knows web_search(query). It must not know who answers it.

The point of the provider chain is that adding Brave/Tavily later touches
backend/core/websearch and nothing above it — not the tool schema, not the
agent, not the planner. These tests pin that boundary, and the failure
behaviour that makes a fallback worth having.

Provider history worth keeping: hand-rolled POSTs to html.duckduckgo.com and
lite.duckduckgo.com answer about two automated queries and then serve an
anti-bot CAPTCHA as HTTP 202 with a normal-looking body. The `ddgs` library
rotates engine backends and survived ten back-to-back queries with zero
failures, which is why the provider wraps the library instead of the endpoint.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import websearch
from backend.core.websearch.base import SearchProvider, SearchResult


class _Stub(SearchProvider):
    def __init__(self, name, results=None, error=None, is_available=True):
        self.name = name
        self._results = results or []
        self._error = error
        self._available = is_available
        self.calls = 0

    def available(self):
        return self._available

    def search(self, query, limit):
        self.calls += 1
        if self._error:
            raise self._error
        return list(self._results)


def _hit(title="T"):
    return [SearchResult(title=title, url="https://example.com", body="b", source="s")]


@pytest.fixture(autouse=True)
def _clean():
    original = list(websearch._PROVIDERS)
    websearch.clear_cache()
    yield
    websearch._PROVIDERS[:] = original
    websearch.clear_cache()


def _use(*providers):
    websearch._PROVIDERS[:] = list(providers)


def test_first_provider_with_results_wins_and_the_rest_are_not_called():
    first, second = _Stub("first", _hit()), _Stub("second", _hit())
    _use(first, second)

    res = websearch.search("q")
    assert res.provider == "first"
    assert second.calls == 0, "a working primary must not cost a second lookup"


def test_a_failing_provider_falls_through_to_the_next():
    broken = _Stub("broken", error=RuntimeError("captcha"))
    backup = _Stub("backup", _hit("from backup"))
    _use(broken, backup)

    res = websearch.search("q")
    assert res.provider == "backup"
    assert res.results[0].title == "from backup"


def test_an_empty_provider_also_falls_through():
    """No results is not the same as an outage, but either way the next
    provider deserves a try."""
    empty, backup = _Stub("empty", []), _Stub("backup", _hit())
    _use(empty, backup)
    assert websearch.search("q").provider == "backup"


def test_unavailable_providers_are_skipped_without_being_called():
    missing = _Stub("missing", _hit(), is_available=False)
    backup = _Stub("backup", _hit())
    _use(missing, backup)

    assert websearch.search("q").provider == "backup"
    assert missing.calls == 0


def test_everything_failing_raises_rather_than_reporting_no_results():
    """An outage and 'nothing matched' need different words to the user."""
    _use(_Stub("a", error=RuntimeError("down")),
         _Stub("b", error=RuntimeError("down too")))
    with pytest.raises(RuntimeError):
        websearch.search("q")


def test_everything_empty_is_not_an_error():
    _use(_Stub("a", []), _Stub("b", []))
    res = websearch.search("q")
    assert not res
    assert res.results == []


def test_a_repeat_query_is_served_from_cache():
    p = _Stub("p", _hit())
    _use(p)
    websearch.search("Same Question")
    websearch.search("same question")   # case-insensitive
    assert p.calls == 1


def test_cache_covers_for_a_later_outage():
    """Throttling mid-conversation must replay the last good results rather
    than going silent."""
    good = _Stub("good", _hit())
    _use(good)
    websearch.search("q")

    key = list(websearch._CACHE)[0]
    websearch._CACHE[key] = (0.0, websearch._CACHE[key][1])   # expire it
    _use(_Stub("broken", error=RuntimeError("429")))

    res = websearch.search("q")
    assert res.cached is True
    assert res.results, "stale results beat no results"


def test_empty_query_never_reaches_a_provider():
    p = _Stub("p", _hit())
    _use(p)
    assert not websearch.search("   ")
    assert p.calls == 0


def test_results_are_flagged_as_external_data():
    """Web text is attacker-controllable; data_sources uses the same flag and
    the Planner's directive keys off it."""
    _use(_Stub("p", _hit()))
    assert websearch.search("q").to_dict()["is_external_data"] is True


def test_duckduckgo_is_tried_before_the_encyclopedia():
    """Ordering is the coverage decision: a general engine finds product docs
    and this week's events; Wikipedia cannot."""
    assert websearch.providers()[0] == "duckduckgo"
    assert "wikipedia" in websearch.providers()


def test_adding_a_provider_needs_no_change_above_this_module():
    """The whole point of the abstraction — a new provider is one list entry
    and the tool schema is untouched."""
    from backend.core.tools.registry import REGISTRY
    import backend.core.tools  # noqa: F401

    before = REGISTRY["search_and_answer"].schema
    _use(_Stub("brave", _hit()), *websearch._PROVIDERS)
    assert websearch.search("q").provider == "brave"
    assert REGISTRY["search_and_answer"].schema == before


def test_search_tools_are_registered():
    from backend.core.tools.registry import REGISTRY
    import backend.core.tools  # noqa: F401

    for name in ("web_search", "search_and_answer"):
        assert name in REGISTRY, f"{name} never reached the registry"
