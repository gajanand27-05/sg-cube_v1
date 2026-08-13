from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import json


def naive_local(dt: datetime) -> datetime:
    """Coerce a datetime to this store's canonical form: naive local time.

    Every row already in Chroma was written by `datetime.now()` — naive local —
    so making aware-UTC the canon would need a migration of the whole store.
    Normalizing at the boundary is the cheaper half of that trade.

    Why it matters: the age subtractions in long_term/timeline/screen_memory
    (`datetime.now() - created`) all sit inside `except` blocks that swallow and
    return []. A single aware timestamp entering the store — a caller passing
    `datetime.now(timezone.utc)`, which several modules elsewhere in the backend
    do produce — therefore does not raise; it silently empties semantic recall.
    """
    return dt if dt.tzinfo is None else dt.astimezone().replace(tzinfo=None)


def parse_ts(value) -> datetime:
    """Read a stored timestamp back as naive local. Accepts an ISO string or a
    datetime, so callers don't have to check which one Chroma handed them."""
    return naive_local(value if isinstance(value, datetime) else datetime.fromisoformat(value))


class MemoryType(str, Enum):
    FACT = "fact"           # Deterministic data (birthday, phone)
    PREFERENCE = "pref"     # User likes/dislikes
    PATTERN = "pattern"     # Successful tool workflow
    DECISION = "decision"   # Past choice made by user/agent
    OUTCOME = "outcome"     # Result of an action (success/fail)
    VISUAL = "visual"       # Screen context observations
    EPISODIC = "episodic"   # Narrative interaction history
    EVENT = "event"         # Discrete timestamped action (opened file, ran tool)
    ACTIVITY = "activity"   # Prolonged user state (working on X)


@dataclass
class MemoryEntry:
    content: str
    mtype: MemoryType
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance: float = 1.0              # Base relevance for ranking
    importance: float = 0.5             # 0.0-1.0: how critical this memory is
    confidence: float = 0.9             # 0.0-1.0: how reliable this memory is
    last_accessed: Optional[datetime] = None
    access_count: int = 0               # How many times retrieved
    source: str = "user"                # "user" | "agent" | "system" | "auto"
    tags: list[str] = field(default_factory=list)
    
    # Lifecycle state
    state: str = "active"               # "active" | "strengthened" | "archived" | "forgotten"
    version: int = 1                    # Increment on updates
    
    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert datetime objects to ISO strings, naive-local so a caller that
        # built the entry with an aware datetime can't poison the store.
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = naive_local(v).isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        # Convert ISO strings back to datetime
        for k in ["timestamp", "last_accessed"]:
            if data.get(k) is not None:
                data[k] = parse_ts(data[k])
        # Handle mtype conversion
        if isinstance(data.get("mtype"), str):
            data["mtype"] = MemoryType(data["mtype"])
        return cls(**data)
    
    def access(self) -> None:
        """Record an access for lifecycle tracking."""
        self.last_accessed = datetime.now()
        self.access_count += 1
    
    def strengthen(self, amount: float = 0.1) -> None:
        """Increase importance/confidence after successful use."""
        self.importance = min(1.0, self.importance + amount)
        self.confidence = min(1.0, self.confidence + amount * 0.5)
        self.state = "strengthened"
        self.version += 1
    
    def decay(self, time_factor: float = 1.0) -> None:
        """Time-based decay for unused memories."""
        self.importance = max(0.1, self.importance - 0.05 * time_factor)
        if self.importance < 0.2 and self.state == "active":
            self.state = "archived"
    
    def merge_with(self, other: "MemoryEntry") -> None:
        """Merge duplicate/similar memory into this one."""
        if other.importance > self.importance:
            self.importance = other.importance
        if other.confidence > self.confidence:
            self.confidence = other.confidence
        self.access_count += other.access_count
        self.version += 1
        # Merge tags
        self.tags = list(set(self.tags) | set(other.tags))
