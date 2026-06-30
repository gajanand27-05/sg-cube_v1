"""Context Builder package."""
from backend.core.context.builder import ContextBuilder, context_builder
from backend.core.context.types import (
    AgentContext,
    RequestContext,
    WindowInfo,
    DetectedObject,
)

__all__ = [
    "ContextBuilder",
    "context_builder",
    "AgentContext",
    "RequestContext",
    "WindowInfo",
    "DetectedObject",
]