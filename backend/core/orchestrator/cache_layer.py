import difflib
from collections import OrderedDict

from backend.core.orchestrator.llm_layer import Intent

# LRU, not a plain dict: this is a process-lifetime module global on the voice
# path. Unbounded, it grows with every distinct utterance for as long as the
# daemon runs, and get_fuzzy's difflib scan below is O(len(_cache)) per miss —
# so the leak is a latency regression, not just memory.
_MAX_ENTRIES = 500
_cache: OrderedDict[str, Intent] = OrderedDict()

# ── Phase D3: Fuzzy cache matching for typos ──
_FUZZY_CUTOFF = 0.8  # 80% similarity threshold


def get(key: str) -> Intent | None:
    intent = _cache.get(key)
    if intent is not None:
        _cache.move_to_end(key)
    return intent


def get_fuzzy(key: str) -> Intent | None:
    """Exact match first, then Levenshtein-style fuzzy match via difflib."""
    if not key:
        return None
    exact = _cache.get(key)
    if exact is not None:
        return exact
    if not _cache:
        return None
    # ponytail: O(n) difflib scan over every key, on every miss. Bounded to
    # _MAX_ENTRIES so the cost has a ceiling instead of growing with uptime.
    # Upgrade path if 500 is still too slow: index keys by length/first token
    # and only score the plausible bucket.
    matches = difflib.get_close_matches(key, _cache.keys(), n=1, cutoff=_FUZZY_CUTOFF)
    if matches:
        _cache.move_to_end(matches[0])
        return _cache[matches[0]]
    return None


def set(key: str, intent: Intent) -> None:
    _cache[key] = intent
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)  # evict least-recently-used


def size() -> int:
    return len(_cache)


def clear() -> None:
    _cache.clear()
