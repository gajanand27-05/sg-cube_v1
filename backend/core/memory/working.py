from typing import Any

class WorkingMemory:
    """Temporary storage for the current multi-step task."""
    def __init__(self):
        self._data: dict[str, Any] = {}

    def set(self, key: str, value: Any):
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def clear(self):
        self._data.clear()

    def render_prompt(self) -> str:
        if not self._data:
            return ""
        items = [f"- {k}: {v}" for k, v in self._data.items()]
        return "Current Task State:\n" + "\n".join(items)
