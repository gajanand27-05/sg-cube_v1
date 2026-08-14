"""DuckDuckGo provider — the default. No API key, no account, no browser.

Uses the `ddgs` library rather than scraping html.duckduckgo.com ourselves.
That distinction is the whole reason this works: hand-rolled POSTs to the
html/ and lite/ endpoints answer about two automated queries and then return
an anti-bot CAPTCHA ("select all squares containing a duck") as HTTP 202 with
a normal-looking body — it does not even read as an error. ddgs rotates across
several engine backends (backend="auto"), which survived ten back-to-back
queries here with zero failures.

Deliberately not a browser. Driving Chrome for search would inherit whichever
profile happens to be active, which on a machine with several signed-in Google
accounts is a coin flip and needs a visible window the user must look at — the
opposite of what a voice-first assistant should do. This provider needs no
session at all.
"""
from __future__ import annotations

import logging

from backend.core.websearch.base import SearchProvider, SearchResult

log = logging.getLogger(__name__)

# Generous: ddgs may try more than one backend before one answers, and the
# whole call is bounded by the tool's own timeout anyway.
_TIMEOUT_S = 12


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def available(self) -> bool:
        try:
            import ddgs  # noqa: F401
        except ImportError:
            log.warning("ddgs not installed — DuckDuckGo search unavailable")
            return False
        return True

    def search(self, query: str, limit: int) -> list[SearchResult]:
        from ddgs import DDGS

        with DDGS(timeout=_TIMEOUT_S) as client:
            raw = client.text(query, max_results=limit, backend="auto")

        results = []
        for item in raw or []:
            url = item.get("href") or item.get("url") or ""
            if not url:
                continue
            results.append(SearchResult(
                title=(item.get("title") or "").strip(),
                url=url,
                body=(item.get("body") or "").strip(),
                source=self.name,
            ))
        return results
