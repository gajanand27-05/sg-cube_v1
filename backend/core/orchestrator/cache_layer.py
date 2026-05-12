from backend.core.orchestrator.llm_layer import Intent

_cache: dict[str, Intent] = {}


def get(key: str) -> Intent | None:
    return _cache.get(key)


def set(key: str, intent: Intent) -> None:
    _cache[key] = intent


def size() -> int:
    return len(_cache)


def clear() -> None:
    _cache.clear()
