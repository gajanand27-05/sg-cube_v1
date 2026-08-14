"""Provider-agnostic search types.

The Brain only ever knows `web_search(query)`. Which engine answers is a
detail behind this interface, so a provider can be swapped or a paid one added
without the agent, the planner or the tool schema changing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class SearchResult:
    """One result. `body` is the snippet the engine returned; `text` is the
    fetched page body, only populated when a caller asks for it."""
    title: str
    url: str
    body: str = ""
    source: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResponse:
    provider: str
    query: str
    results: list[SearchResult] = field(default_factory=list)
    #  True when served from cache rather than a live call.
    cached: bool = False

    def __bool__(self) -> bool:
        return bool(self.results)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "query": self.query,
            "cached": self.cached,
            "results": [r.to_dict() for r in self.results],
            # Everything here is text from the open web. data_sources uses the
            # same flag, and the Planner's directive keys off it to treat the
            # content as data rather than as instructions.
            "is_external_data": True,
        }


class SearchProvider(ABC):
    """A source of web results.

    Implementations must not raise for "no results" — that is an empty list,
    a normal outcome. Raise only when the provider itself failed (network,
    throttling, markup change), so the chain can distinguish "nothing matched"
    from "this provider is down" and decide whether to try the next one.
    """

    name: str = "provider"

    @abstractmethod
    def search(self, query: str, limit: int) -> list[SearchResult]: ...

    def available(self) -> bool:
        """False when the provider cannot run at all — a missing dependency or
        an unset API key. Unavailable providers are skipped silently; failing
        ones are logged."""
        return True
