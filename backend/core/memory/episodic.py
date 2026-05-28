import json
import logging
from typing import List

import httpx

from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.manager import memory as memory_manager
from backend.server.config import settings

log = logging.getLogger(__name__)


class EpisodeSummarizer:
    """The 'Learning Layer' - extracts patterns and facts from interactions."""

    async def summarize_and_store(self, user_query: str, interactions: List[dict]):
        """Analyze a finished interaction and store key takeaways."""
        if not interactions:
            return

        # Prepare summary prompt for the model
        url = f"{settings.ollama_url.rstrip('/')}/api/chat"
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
        payload = {
            "model": settings.ollama_model,  # phi3
            "messages": [{"role": "system", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(url, json=payload)
            r.raise_for_status()
            res = r.json()
            content = json.loads(res.get("message", {}).get("content") or "{}")

            # Store extracted facts
            for fact in content.get("facts", []):
                memory_manager.remember_fact(fact, metadata={"source": "episodic_summarizer"})

            # Store extracted patterns in EM (using LTM with PATTERN type)
            for pattern in content.get("patterns", []):
                entry = MemoryEntry(
                    content=pattern,
                    mtype=MemoryType.PATTERN,
                    metadata={"query": user_query}
                )
                memory_manager.ltm.store(entry)
                log.info(f"Learned new pattern: {pattern}")

        except Exception as e:
            log.warning(f"Episodic summarization failed: {e}")


# Global instance
summarizer = EpisodeSummarizer()
