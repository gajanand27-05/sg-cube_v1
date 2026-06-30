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


class RoutingPolicy:
    """Maps TaskType -> backend name. Configurable via settings."""
    
    def __init__(self, mapping: dict[TaskType, str] | None = None):
        self._mapping = mapping or self._default_mapping()

    def _default_mapping(self) -> dict[TaskType, str]:
        """Default routing — prefers local for fast tasks, cloud for reasoning."""
        return {
            TaskType.INTENT_CLASSIFICATION: "ollama",      # phi3 - fast, local
            TaskType.VERIFICATION: "ollama",               # phi3 - fast, local
            TaskType.EMBEDDING: "embedding",               # ollama embeddings
            TaskType.PLANNING: "gemini" if settings.gemini_api_key else "openrouter",
            TaskType.CODING: "gemini" if settings.gemini_api_key else "openrouter",
            TaskType.SUMMARIZATION: "ollama",              # local summarization
            TaskType.CHAT: "openrouter" if settings.openrouter_api_key else "gemini" if settings.gemini_api_key else "ollama",
            TaskType.GENERAL: "openrouter" if settings.openrouter_api_key else "gemini" if settings.gemini_api_key else "ollama",
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