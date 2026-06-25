import difflib

from backend.core.orchestrator.llm_layer import Intent

_cache: dict[str, Intent] = {}

# ── Phase D3: Fuzzy cache matching for typos ──
_FUZZY_CUTOFF = 0.8  # 80% similarity threshold


def get(key: str) -> Intent | None:
    return _cache.get(key)


def get_fuzzy(key: str) -> Intent | None:
    """Exact match first, then Levenshtein-style fuzzy match via difflib."""
    if not key:
        return None
    exact = _cache.get(key)
    if exact is not None:
        return exact
    if not _cache:
        return None
    matches = difflib.get_close_matches(key, _cache.keys(), n=1, cutoff=_FUZZY_CUTOFF)
    if matches:
        return _cache[matches[0]]
    return None


def set(key: str, intent: Intent) -> None:
    _cache[key] = intent


def size() -> int:
    return len(_cache)


def clear() -> None:
    _cache.clear()
