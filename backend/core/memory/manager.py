import logging
from datetime import datetime
from typing import List, Optional

from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.long_term import LongTermMemory
from backend.core.memory.short_term import ShortTermMemory
from backend.core.memory.working import WorkingMemory
from backend.core.memory.screen_memory import screen_memory
from backend.core.memory.timeline import timeline

log = logging.getLogger(__name__)


class MemoryManager:
    """The central hub for all memory tiers in SG_CUBE."""

    def __init__(self):
        self.stm = ShortTermMemory()
        self.wm = WorkingMemory()
        self.ltm = LongTermMemory()
        self.timeline = timeline

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
        
        # 3. Get relevant facts
        try:
            facts = self.ltm.search(query, limit=3)
            fact_str = "\n".join([f"- {f.content}" for f in facts])
        except Exception:
            fact_str = ""

        # 4. Get visual situational awareness (Historical RAG)
        try:
            visuals = screen_memory.search_visual(query, limit=2)
            visual_str = "\n".join([f"- {v.content}" for v in visuals])
        except Exception:
            visual_str = ""

        # 5. Get recent Timeline events (Chronological Narrative)
        try:
            recent_events = self.timeline.get_recent_timeline(limit=5)
            
            # If the user asks about the past specifically, also perform semantic search
            temporal_keywords = ["doing", "last", "ago", "was", "yesterday", "before", "history"]
            if any(k in query.lower() for k in temporal_keywords):
                past_events = self.timeline.search_timeline(query, limit=3)
                # Merge and unique
                seen = {e.content for e in recent_events}
                for e in past_events:
                    if e.content not in seen:
                        recent_events.append(e)
            
            timeline_lines = []
            # Sort again after merge
            recent_events.sort(key=lambda x: x.timestamp, reverse=True)
            
            for e in recent_events[:8]: # Cap at 8 unique items
                delta = datetime.now = datetime.now()
                if delta.total_seconds() < 60:
                    time_str = "Just now"
                elif delta.total_seconds() < 3600:
                    time_str = f"{int(delta.total_seconds() // 60)}m ago"
                elif delta.total_seconds() < 86400:
                    time_str = f"{int(delta.total_seconds() // 3600)}h ago"
                else:
                    time_str = e.timestamp.strftime("%Y-%m-%d %H:%M")
                
                timeline_lines.append(f"[{time_str}] {e.content}")
            timeline_str = "\n".join(timeline_lines)
        except Exception:
            timeline_str = ""

        context = "── SYSTEM MEMORY ──────────────────────────────────\n"
        if fact_str:
            context += f"Relevant Facts:\n{fact_str}\n"
        
        if timeline_str:
            context += f"\nRecent Activity Timeline:\n{timeline_str}\n"

        if visual_str:
            context += f"\nSituational Context (Semantic):\n{visual_str}\n"
            
        if wm_context:
            context += f"\n{wm_context}\n"
        context += "──────────────────────────────────────────────────"
        
        return context

    # ===== Enhanced Memory API =====
    
    def remember(self, content: str, mtype: MemoryType = MemoryType.FACT, 
                 importance: float = 0.5, confidence: float = 0.9,
                 tags: list[str] = None, source: str = "user",
                 metadata: dict = None) -> str:
        """Store a memory with full metadata."""
        entry = MemoryEntry(
            content=content,
            mtype=mtype,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            source=source,
            metadata=metadata or {},
        )
        self.ltm.store(entry)
        return entry.metadata.get("id", "unknown")

    def recall(self, query: str, mtype: MemoryType = None, limit: int = 5,
               min_importance: float = 0.0) -> List[MemoryEntry]:
        """Retrieve relevant memories with importance scoring."""
        results = self.ltm.search(query, mtype=mtype, limit=limit, min_importance=min_importance)
        
        # Filter by importance and apply access tracking
        filtered = []
        for entry in results:
            if entry.importance >= min_importance:
                entry.access()
                filtered.append(entry)
        
        # Sort by combined score
        filtered.sort(key=lambda e: e.relevance * e.importance * e.confidence, reverse=True)
        return filtered[:limit]

    def forget(self, memory_id: str) -> bool:
        """Mark a memory as forgotten (soft delete)."""
        return False  # Placeholder - requires ID tracking

    def learn(self, user_query: str, tool_results: list[dict], success: bool = True) -> None:
        """Learn from successful (or failed) tool executions."""
        if not success or not tool_results:
            return
        
        tools_used = [r.get("name", "unknown") for r in tool_results]
        pattern = f"For '{user_query}': {', '.join(tools_used)}"
        
        entry = MemoryEntry(
            content=pattern,
            mtype=MemoryType.PATTERN,
            importance=0.7,
            confidence=0.8,
            tags=["learned", "auto"],
            source="auto",
            metadata={"original_query": user_query, "tools": tools_used},
        )
        entry.strengthen(0.1)
        self.ltm.store(entry)

    def strengthen_memory(self, query: str, amount: float = 0.1) -> int:
        """Strengthen memories matching a query (e.g., after successful use)."""
        results = self.recall(query, limit=10, min_importance=0.0)
        count = 0
        for entry in results:
            entry.strengthen(amount)
            self.ltm.strengthen_memory(entry.metadata.get("id", ""), amount)
            count += 1
        return count

    def consolidate_memories(self) -> dict:
        """Periodic memory consolidation: merge duplicates, decay old, archive junk."""
        decayed = self.ltm.decay_memories()
        all_facts = self.ltm.get_all(MemoryType.FACT)
        all_prefs = self.ltm.get_all(MemoryType.PREFERENCE)
        all_patterns = self.ltm.get_all(MemoryType.PATTERN)
        
        return {
            "facts": len(all_facts),
            "preferences": len(all_prefs),
            "patterns": len(all_patterns),
            "decayed": decayed,
            "status": "consolidation_complete",
        }

    def search_explainable(self, query: str, mtype: MemoryType = None, 
                          limit: int = 5) -> List[dict]:
        """Search with detailed explainable scoring breakdown."""
        return self.ltm.search_explainable(query, mtype=mtype, limit=limit)


# Global instance
memory = MemoryManager()
