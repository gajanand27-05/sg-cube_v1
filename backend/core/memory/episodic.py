import json
import logging
from typing import List

from backend.ai_modules.llm import get_provider
from backend.ai_modules.llm.routing import TaskType
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.manager import memory as memory_manager
from backend.server.config import settings

log = logging.getLogger(__name__)


def _as_text(item) -> str:
    """Coerce one extracted fact/pattern to a string.

    The model does not reliably return strings here. Observed live:

        Failed to store semantic memory: Expected document to be a str, got
        {'workflow_name': '...', 'steps': [...], 'tools': ['duckduckgo']}

    Chroma rejects a dict document, so every one of those was thrown away
    after the LLM call had already been paid for — the layer was doing its
    work and then losing it. The prompt asks for strings; this is the floor
    for when it obliges with structure instead.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        # Prefer a human-readable field if the model supplied one.
        for key in ("workflow", "description", "summary", "pattern", "fact",
                    "workflow_name", "name", "text"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, (list, tuple)):
        return " ".join(_as_text(x) for x in item).strip()
    return str(item).strip()


class EpisodeSummarizer:
    """The 'Learning Layer' - extracts patterns and facts from interactions."""

    async def summarize_and_store(self, user_query: str, interactions: List[dict]):
        """Analyze a finished interaction and store key takeaways."""
        if not interactions:
            return
        if not settings.enable_episodic_summarizer:
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
                text = _as_text(fact)
                if not text:
                    continue
                memory_manager.remember_fact(text, metadata={"source": "episodic_summarizer"})

            # Store extracted patterns in EM (using LTM with PATTERN type)
            for pattern in data.get("patterns", []):
                text = _as_text(pattern)
                if not text:
                    continue
                entry = MemoryEntry(
                    content=text,
                    mtype=MemoryType.PATTERN,
                    metadata={"query": user_query}
                )
                memory_manager.ltm.store(entry)
                log.info(f"Learned new pattern: {text}")

        except Exception as e:
            # Log the TYPE, not just str(e). This fired repeatedly in live use
            # as the bare line "Episodic summarization failed:" with nothing
            # after the colon — several exceptions here stringify to empty
            # (a bare raise, a cancelled task) and the message alone said
            # nothing at all about what went wrong. exc_info gives the
            # traceback without changing the level: this is a
            # learning-layer nicety, and it must never look like a turn failed.
            log.warning(
                "Episodic summarization failed: %s: %s",
                type(e).__name__, e or "(no message)", exc_info=True,
            )


# Global instance
summarizer = EpisodeSummarizer()
