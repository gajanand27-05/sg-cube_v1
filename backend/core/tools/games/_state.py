"""Shared game state store — persists across turns within a session."""
from typing import Any

_state: dict[str, Any] = {}
