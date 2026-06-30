"""Context types for the intelligence pipeline."""
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime

from backend.core.tools.registry import Tool
from backend.core.memory.base import MemoryEntry
from backend.core.caps import Capability


@dataclass
class WindowInfo:
    """Active window information."""
    title: str
    app: str
    hwnd: int | None = None
    bounds: tuple[int, int, int, int] | None = None  # left, top, right, bottom


@dataclass
class DetectedObject:
    """Visual object detected by vision loop."""
    label: str
    confidence: float
    bbox: tuple[int, int, int, int] | None = None  # x, y, w, h
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentContext:
    """Complete context passed to all agents in the pipeline."""
    
    # Input
    user_intent: str
    input_mode: str = "voice"  # "voice" | "text" | "proactive"
    
    # Conversation history (STM)
    recent_conversation: list[dict] = field(default_factory=list)
    
    # Long-term memory (semantic)
    long_term_memory: list[MemoryEntry] = field(default_factory=list)
    
    # Visual context
    active_window: WindowInfo | None = None
    screen_objects: list[DetectedObject] = field(default_factory=list)
    running_apps: list[str] = field(default_factory=list)
    
    # Timeline (chronological)
    recent_events: list[MemoryEntry] = field(default_factory=list)
    
    # Available capabilities
    available_tools: list[Tool] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    
    # Routing confidence
    confidence: float = 1.0
    
    # Metadata
    user_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class RequestContext:
    """Input to ContextBuilder."""
    user_intent: str
    user_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    input_mode: str = "voice"
    metadata: dict = field(default_factory=dict)