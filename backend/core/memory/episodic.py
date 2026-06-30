import json
import logging
from typing import List

from backend.ai_modules.llm import get_provider
from backend.ai_modules.llm.routing import TaskType
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.manager import memory as memory_manager

log = logging.getLogger(__name__)


class EpisodeSummarizer:
    """The 'Learning Layer' - extracts patterns and facts from interactions."""

    async def summarize_and_store(self, user_query: str, interactions: List[dict]):
        """Analyze a finished interaction and store key takeaways."""
        if not interactions:
            return

        prompt = f"""Analyze this AI-User interaction.
User Query: "{user_query}"
Actions Taken: {json.dumps(interactions)}

Extract two things:
1. NEW FACTS: Any persistent info about the user (names, dates, preferences).
2. SUCCESSFUL PATTERN: If a specific tool sequence worked well, summarize the 'workflow'.

Reply with a single JSON object:
{{
  "facts": ["..."],
  "patterns": ["..."]
}}
"""

        try:
            llm = get_provider()
            content = await llm.generate(prompt, task=TaskType.SUMMARIZATION, json_mode=True, temperature=0.0)
            data = json.loads(content)

            # Store extracted facts
            for fact in data.get("facts", []):
                memory_manager.remember_fact(fact, metadata={"source": "episodic_summarizer"})

            # Store extracted patterns in EM (using LTM with PATTERN type)
            for pattern in data.get("patterns", []):
                entry = MemoryEntry(
                    content=pattern,
                    mtype=MemoryType.PATTERN,
                    metadata={"query": user_query}
                )
                memory_manager.ltm.store(entry)
                log.info(f"Learned new pattern: {pattern}")

        except Exception as e:
            log.warning(f"Episodic summarization failed: {e}")
