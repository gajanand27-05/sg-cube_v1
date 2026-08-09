"""Brain — transport-agnostic orchestrator for the intelligence pipeline.

All inputs (voice, text, proactive, MCP, REST) funnel through Brain.run().
"""
import uuid
import time
import re
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, List

from backend.core.agents.commander import commander
from backend.core.agent.context import ConversationContext
from backend.core.context.builder import context_builder
from backend.core.context.types import RequestContext
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.core.memory.manager import memory as memory_manager


@dataclass
class BrainRequest:
    """Input to the brain from any transport layer."""
    user_id: str
    input_text: str
    input_mode: str = "text"  # "voice" | "text" | "proactive"
    session_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolCall:
    """Record of a tool/capability execution."""
    name: str
    args: dict
    result: Any = None
    latency_ms: int = 0
    status: str = "success"


@dataclass
class BrainChunk:
    """Streaming chunk from brain."""
    type: str  # "token", "tool_start", "tool_end", "final", "error"
    content: Any = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BrainResponse:
    """Final output from the brain (for non-streaming callers)."""
    spoken_text: str
    intent: dict
    tool_calls: list[ToolCall] = field(default_factory=list)
    execution_trace: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    metadata: dict = field(default_factory=dict)


class Brain:
    """Central orchestrator — wraps Commander + ContextBuilder + Memory."""

    def __init__(self):
        self.commander = commander

    async def run(self, request: BrainRequest) -> BrainResponse:
        """Non-streaming entry point — runs the full intelligence pipeline."""
        async for chunk in self.run_stream(request):
            if chunk.type == "final":
                return chunk.content
        # Fallback
        return BrainResponse(spoken_text="", intent={}, tool_calls=[], execution_trace=[], latency_ms=0)

    async def run_stream(self, request: BrainRequest) -> AsyncGenerator[BrainChunk, None]:
        """Streaming entry point — yields chunks as they're ready."""
        t0 = time.perf_counter()
        request_id = str(uuid.uuid4())[:8]

        # Build unified context
        context_request = RequestContext(
            user_intent=request.input_text,
            user_id=request.user_id,
            session_id=request.session_id,
            request_id=request_id,
            input_mode=request.input_mode,
            metadata=request.metadata,
        )
        agent_context = await context_builder.collect(context_request)

        yield BrainChunk(type="context_ready", metadata={"latency_ms": int((time.perf_counter() - t0) * 1000)})

        # Ponytail-fix: pass session_id into the conversation context so Commander
        # can stamp RequestContext.session_id without a hasattr fallback.
        conversation = ConversationContext(session_id=request.session_id)

        # Run Commander pipeline with streaming
        tool_records = []
        sentence_buffer = ""

        async for chunk in self.commander.run_stream(request.input_text, conversation, request.user_id):
            if chunk.type == "token":
                # Raw planner tokens: UI ticker and the planner_first_token
                # latency mark. NOT spoken — they are a JSON envelope, and
                # buffering them here is what made Piper read
                # `{"final_response":"Got it!` aloud. Speech comes from "prose".
                yield BrainChunk(type="token", content=chunk.content)

            elif chunk.type == "prose":
                sentence_buffer += chunk.content

                # Phase 4B: emit tts_ready every time a sentence completes,
                # not just the first. Downstream drains a per-sentence queue
                # so time-to-first-audio drops while later sentences arrive.
                if self._is_sentence_complete(sentence_buffer):
                    yield BrainChunk(type="tts_ready", content=sentence_buffer.strip())
                    sentence_buffer = ""

            elif chunk.type == "tool_start":
                yield BrainChunk(type="tool_start", content=chunk.content, metadata=chunk.metadata)
            
            elif chunk.type == "tool_end":
                tool_records.append(chunk.content)
                yield BrainChunk(type="tool_end", content=chunk.content, metadata=chunk.metadata)
            
            elif chunk.type == "final_response":
                # Final response from planner
                if sentence_buffer.strip():
                    yield BrainChunk(type="tts_ready", content=sentence_buffer.strip())
                yield BrainChunk(type="final", content=self._build_response(chunk.content, tool_records, t0, request_id, request))
                return

        # Build final response if not already yielded
        latency_ms = int((time.perf_counter() - t0) * 1000)
        tool_calls = self._build_tool_calls(tool_records)
        execution_trace = self._build_execution_trace(tool_calls)
        
        response = BrainResponse(
            spoken_text=sentence_buffer.strip() if sentence_buffer else "Done.",
            intent={"action": "agent_complete", "target": request.input_text, "args": {}},
            tool_calls=tool_calls,
            execution_trace=execution_trace,
            latency_ms=latency_ms,
            metadata={"request_id": request_id, "input_mode": request.input_mode}
        )
        yield BrainChunk(type="final", content=response)

    def _is_sentence_complete(self, text: str) -> bool:
        """Check if text ends with a sentence boundary."""
        text = text.strip()
        return bool(re.search(r'[.!?]\s*$', text)) and len(text) > 10

    def _build_response(self, spoken: str, tool_records: list, t0: float, request_id: str, request: BrainRequest) -> BrainResponse:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        tool_calls = self._build_tool_calls(tool_records)
        execution_trace = self._build_execution_trace(tool_calls)
        return BrainResponse(
            spoken_text=spoken,
            intent={"action": "agent_complete", "target": request.input_text, "args": {}},
            tool_calls=tool_calls,
            execution_trace=execution_trace,
            latency_ms=latency_ms,
            metadata={"request_id": request_id, "input_mode": request.input_mode}
        )

    def _build_tool_calls(self, tool_records: list) -> list[ToolCall]:
        calls = []
        for record in tool_records:
            calls.append(ToolCall(
                name=record.get("name", "unknown"),
                args=record.get("args", {}),
                result=record.get("result"),
                latency_ms=record.get("result", {}).get("latency_ms", 0) if isinstance(record.get("result"), dict) else 0,
                status=getattr(record.get("result"), "status", record.get("result", {}).get("status", "success")) if record.get("result") else "error"
            ))
        return calls

    def _build_execution_trace(self, tool_calls: list[ToolCall]) -> list[dict]:
        return [
            {"stage": "context_build", "latency_ms": 0},
            {"stage": "planner", "latency_ms": 0},
            {"stage": "guardian", "latency_ms": 0},
            {"stage": "operator", "latency_ms": sum(tc.latency_ms for tc in tool_calls)},
            {"stage": "tts", "latency_ms": 0},
        ]

    # ===== Unified Memory API =====
    
    def remember(self, content: str, mtype: MemoryType = MemoryType.FACT, 
                 importance: float = 0.5, confidence: float = 0.9,
                 tags: list[str] = None, source: str = "user",
                 metadata: dict = None) -> str:
        """Store a fact/preference/pattern in long-term memory.
        
        Returns the memory ID."""
        entry = MemoryEntry(
            content=content,
            mtype=mtype,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            source=source,
            metadata=metadata or {},
        )
        memory_manager.ltm.store(entry)
        return str(entry.metadata.get("id", "unknown"))

    def recall(self, query: str, mtype: MemoryType = None, limit: int = 5,
               min_importance: float = 0.0) -> List[MemoryEntry]:
        """Retrieve relevant memories, honoring LTM.search's composite ranking."""
        # Delegated, not reimplemented. This used to re-sort ltm.search's output
        # by `relevance * importance * confidence`, which dropped the semantic
        # and temporal signals entirely (`relevance` is a stored constant, 1.0
        # for every entry the writers create) — so an off-topic high-importance
        # memory outranked the one that actually answered the query. The audit
        # recorded that as fixed; the fix had gone to MemoryManager.recall and
        # never to this copy. Three methods on this class had drifted the same
        # way, so they now share one implementation instead of four.
        return memory_manager.recall(query, mtype=mtype, limit=limit,
                                     min_importance=min_importance)

    def forget(self, memory_id: str) -> bool:
        """Delete a memory by id. True if it existed and was removed."""
        # Was `return False` unconditionally, with a "placeholder" comment. The
        # audit logged that as fixed, and it was — on MemoryManager.forget, not
        # on this copy. Delegating rather than re-implementing so there is one
        # behaviour, not two that drift.
        return memory_manager.forget(memory_id)

    def learn(self, user_query: str, tool_results: list[dict], success: bool = True) -> None:
        """Learn from successful (or failed) tool executions.
        
        Extracts patterns and stores as PATTERN memory type."""
        if not success or not tool_results:
            return
        
        # Build pattern description
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
        entry.strengthen(0.1)  # Boost because it worked
        memory_manager.ltm.store(entry)

    def strengthen_memory(self, query: str, amount: float = 0.1) -> int:
        """Strengthen memories matching a query (e.g., after successful use)."""
        # Was `ltm.store(entry)` on an entry that already has an id. store()
        # calls collection.add(), not upsert, so the strengthened importance
        # was never persisted — and on a Chroma build that accepts duplicate
        # ids it would instead have re-grown the duplicate rows that
        # T-memory-duplicate-rows spent a session purging. MemoryManager
        # already does this correctly via ltm.strengthen_memory(id, amount).
        return memory_manager.strengthen_memory(query, amount)

    def consolidate_memories(self) -> dict:
        """Periodic memory consolidation: merge duplicates, decay old, archive junk."""
        # This would be called periodically (e.g., every few hours)
        # For now, return stats
        all_facts = memory_manager.ltm.get_all(MemoryType.FACT)
        all_prefs = memory_manager.ltm.get_all(MemoryType.PREFERENCE)
        all_patterns = memory_manager.ltm.get_all(MemoryType.PATTERN)
        
        return {
            "facts": len(all_facts),
            "preferences": len(all_prefs),
            "patterns": len(all_patterns),
            "status": "consolidation_scheduled",
        }


# Global instance
brain = Brain()