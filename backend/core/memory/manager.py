import logging
from typing import List, Optional

from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.long_term import LongTermMemory
from backend.core.memory.short_term import ShortTermMemory
from backend.core.memory.working import WorkingMemory

log = logging.getLogger(__name__)


class MemoryManager:
    """The central hub for all memory tiers in SG_CUBE."""

    def __init__(self):
        self.stm = ShortTermMemory()
        self.wm = WorkingMemory()
        self.ltm = LongTermMemory()

    def remember_fact(self, content: str, metadata: Optional[dict] = None):
        """Explicitly store a fact in Long-Term Memory."""
        entry = MemoryEntry(content=content, mtype=MemoryType.FACT, metadata=metadata or {})
        self.ltm.store(entry)
        log.info(f"Fact remembered: {content}")

    def remember_preference(self, content: str, metadata: Optional[dict] = None):
        """Explicitly store a user preference."""
        entry = MemoryEntry(content=content, mtype=MemoryType.PREFERENCE, metadata=metadata or {})
        self.ltm.store(entry)
        log.info(f"Preference remembered: {content}")

    def get_relevant_context(self, query: str) -> str:
        """Retrieve relevant memories to inject into the Agent's prompt."""
        # 1. Get recent session history
        stm_context = self.stm.render()
        
        # 2. Get working state
        wm_context = self.wm.render_prompt()
        
        # 3. Get relevant facts (Simplified search for now)
        try:
            facts = self.ltm.search(query, limit=3)
            fact_str = "\n".join([f"- {f.content}" for f in facts])
        except Exception:
            fact_str = ""

        context = "── SYSTEM MEMORY ──────────────────────────────────\n"
        if fact_str:
            context += f"Relevant Facts:\n{fact_str}\n"
        if wm_context:
            context += f"\n{wm_context}\n"
        context += "──────────────────────────────────────────────────"
        
        return context


# Global instance
memory = MemoryManager()
