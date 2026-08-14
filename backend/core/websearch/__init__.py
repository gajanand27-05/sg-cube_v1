"""Web search, provider-agnostic.

    search("who won the 2024 t20 world cup") -> SearchResponse

Providers are tried in order until one returns results. Today that is
DuckDuckGo (keyless, general web) then Wikipedia (keyless, encyclopedic, fails
independently). A paid provider — Brave, Tavily, Serper — becomes another
entry in _PROVIDERS and nothing above this module changes: not the tool
schema, not the agent, not the planner.

Ordering is deliberate. The first provider that returns anything wins, so the
list runs best-coverage-first and the fallbacks exist to survive an outage,
not to improve results.

Caching is here rather than in a provider so a repeated question costs one
lookup regardless of which provider answered it.
"""
from __future__ import annotations

import logging
import time

from backend.core.websearch.base import SearchProvider, SearchResponse, SearchResult
from backend.core.websearch.duckduckgo import DuckDuckGoProvider
from backend.core.websearch.wikipedia import WikipediaProvider

log = logging.getLogger(__name__)

__all__ = ["SearchProvider", "SearchResponse", "SearchResult", "search",
           "providers", "clear_cache"]

_PROVIDERS: list[SearchProvider] = [
    DuckDuckGoProvider(),
    WikipediaProvider(),
]

_TTL_S = 900.0                       # 15min
_CACHE: dict[tuple[str, int], tuple[float, SearchResponse]] = {}


def providers() -> list[str]:
    """Names of registered providers, in the order they are tried."""
    return [p.name for p in _PROVIDERS]


def clear_cache() -> None:
    """Test-only. Not exposed as a tool."""
    _CACHE.clear()


def search(query: str, limit: int = 5) -> SearchResponse:
    """Search the web. Returns an empty SearchResponse if nothing matched or
    every provider failed — callers decide how to phrase that.

    A cached response is served when a live attempt fails, so throttling
    mid-conversation replays the last good results instead of going silent.
    """
    query = (query or "").strip()
    if not query:
        return SearchResponse(provider="none", query=query)

    key = (query.lower(), limit)
    hit = _CACHE.get(key)
    if hit is not None and time.monotonic() - hit[0] <= _TTL_S:
        cached = hit[1]
        return SearchResponse(cached.provider, cached.query, cached.results, cached=True)

    failures: list[str] = []
    for provider in _PROVIDERS:
        if not provider.available():
            continue
        try:
            results = provider.search(query, limit)
        except Exception as e:
            # A provider being down is not the query's fault — note it and try
            # the next one.
            failures.append(f"{provider.name}: {type(e).__name__}: {e}")
            log.warning("search provider %s failed: %s", provider.name, e)
            continue

        if results:
            response = SearchResponse(provider.name, query, results)
            _CACHE[key] = (time.monotonic(), response)
            if failures:
                log.info("search answered by %s after %d failure(s)",
                         provider.name, len(failures))
            return response

    if hit is not None:
        log.warning("all providers failed for %r; serving stale results", query)
        stale = hit[1]
        return SearchResponse(stale.provider, stale.query, stale.results, cached=True)

    if failures:
        # Every provider errored — that is an outage, not an empty result set,
        # and the caller should say so rather than "I found nothing".
        raise RuntimeError("; ".join(failures))

    return SearchResponse(provider="none", query=query)
