from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class MemoryType(str, Enum):
    FACT = "fact"           # Deterministic data (birthday, phone)
    PREFERENCE = "pref"     # User likes/dislikes
    PATTERN = "pattern"     # Successful tool workflow
    DECISION = "decision"   # Past choice made by user/agent
    OUTCOME = "outcome"     # Result of an action (success/fail)


@dataclass
class MemoryEntry:
    content: str
    mtype: MemoryType
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance: float = 1.0  # Used for ranking
