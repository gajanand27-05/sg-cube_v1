"""Routing Policy — maps task types to backend names."""
from enum import Enum
from typing import Any

from backend.server.config import settings


class TaskType(str, Enum):
    """Task categories for routing."""
    # Fast, local tasks
    INTENT_CLASSIFICATION = "intent_classification"    # route user input -> intent
    VERIFICATION = "verification"                       # guardian verification
    EMBEDDING = "embedding"                             # vector embeddings
    
    # Reasoning / coding tasks
    PLANNING = "planning"                               # planner agent
    CODING = "coding"                                   # code generation
    SUMMARIZATION = "summarization"                     # summarize content
    
    # General conversation
    CHAT = "chat"                                       # general response
    GENERAL = "general"                                 # fallback


def _cloud_or(fallback: str) -> str:
    """Reasoning-class tasks go to Ollama Cloud when a key is configured.

    Gemini stays ahead of the local fallback only if its key is set; with no
    cloud key at all the whole chain degrades to local Ollama rather than
    failing, so the assistant still answers on a laptop GPU.
    """
    if settings.ollama_api_key:
        return "ollama_cloud"
    if settings.gemini_api_key:
        return "gemini"
    return fallback


class RoutingPolicy:
    """Maps TaskType -> backend name. Configurable via settings."""
    
    def __init__(self, mapping: dict[TaskType, str] | None = None):
        self._mapping = mapping or self._default_mapping()

    def _default_mapping(self) -> dict[TaskType, str]:
        """Default routing — prefers local for fast tasks, cloud for reasoning."""
        return {
            TaskType.INTENT_CLASSIFICATION: "ollama",
            TaskType.VERIFICATION: "ollama",
            TaskType.EMBEDDING: "embedding",
            TaskType.PLANNING: _cloud_or("ollama"),
            TaskType.CODING: _cloud_or("ollama"),
            TaskType.SUMMARIZATION: "ollama",
            TaskType.CHAT: _cloud_or("ollama"),
            TaskType.GENERAL: _cloud_or("ollama"),
        }

    def select(self, task: TaskType) -> str:
        """Get backend name for a task."""
        return self._mapping.get(task, self._mapping[TaskType.GENERAL])

    def override(self, task: TaskType, backend: str) -> None:
        """Override routing for a specific task."""
        self._mapping[task] = backend

    def get_mapping(self) -> dict[str, str]:
        return {k.value: v for k, v in self._mapping.items()}


def build_default_policy() -> RoutingPolicy:
    """Build policy from settings."""
    return RoutingPolicy()