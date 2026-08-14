"""Wikipedia provider — the fallback when the search engine is unreachable.

Narrower than a search engine by design: encyclopedic subjects only, nothing
about live events, product docs or anything published this week. It earns its
place purely because it fails independently of DuckDuckGo — different host,
different infrastructure, different throttling — so the assistant can still
answer "what is quantum computing" when the primary is down.

Returns article intros as snippets, so downstream synthesis treats it exactly
like any other provider's results.
"""
from __future__ import annotations

import logging

import httpx

from backend.core.websearch.base import SearchProvider, SearchResult

log = logging.getLogger(__name__)

_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia's API policy asks for an agent that identifies the software; a
# generic browser UA is what gets anonymous traffic throttled.
_HEADERS = {
    "User-Agent": "SG_CUBE/1.0 (personal voice assistant; +https://github.com/sg-cube)",
    "Accept": "application/json",
}
_TIMEOUT_S = 8.0
_EXTRACT_CHARS = 1500


def _get_json(client: httpx.Client, params: dict) -> dict:
    """GET the MediaWiki API, raising a speakable error rather than a parser
    one. The API answers 429 as text/plain, so calling .json() blind raised
    JSONDecodeError and the user heard a stack-trace-shaped message instead of
    'I'm being rate limited'."""
    r = client.get(_API, params=params)
    if r.status_code == 429:
        raise RuntimeError("Wikipedia is rate-limiting this machine")
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        raise RuntimeError(f"Wikipedia returned {ctype or 'an unknown type'}, not JSON")
    return r.json()


class WikipediaProvider(SearchProvider):
    name = "wikipedia"

    def search(self, query: str, limit: int) -> list[SearchResult]:
        with httpx.Client(timeout=_TIMEOUT_S, headers=_HEADERS,
                          follow_redirects=True) as c:
            found = _get_json(c, {
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": limit,
            })
            titles = [h["title"] for h in
                      found.get("query", {}).get("search", []) if h.get("title")]
            if not titles:
                return []

            pages = _get_json(c, {
                "action": "query", "prop": "extracts", "exintro": 1,
                "explaintext": 1, "format": "json", "titles": "|".join(titles),
            }).get("query", {}).get("pages", {})

        # Keep search-rank order: the extracts endpoint keys pages by id, so
        # iterating the dict put 'Mojo (programming language)' ahead of
        # 'Python (programming language)' for a question about Python.
        by_title = {p.get("title"): p for p in pages.values()}
        results = []
        for t in titles:
            page = by_title.get(t)
            if not page:
                continue
            extract = (page.get("extract") or "").strip()
            if not extract:
                continue
            results.append(SearchResult(
                title=t,
                url=f"https://en.wikipedia.org/wiki/{t.replace(' ', '_')}",
                body=extract[:_EXTRACT_CHARS],
                source=self.name,
            ))
        return results
