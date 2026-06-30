"""Brain — transport-agnostic orchestrator for the intelligence pipeline.

All inputs (voice, text, proactive, MCP, REST) funnel through Brain.run().
"""
import uuid
import time
import re
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from backend.core.agents.commander import commander
from backend.core.agent.context import ConversationContext
from backend.core.context.builder import context_builder
from backend.core.context.types import RequestContext


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

        # Create conversation context for Commander
        conversation = ConversationContext()

        # Run Commander pipeline with streaming
        tool_records = []
        sentence_buffer = ""
        tts_started = False

        async for chunk in self._run_commander_stream(request.input_text, conversation, request.user_id):
            if chunk.type == "token":
                sentence_buffer += chunk.content
                yield BrainChunk(type="token", content=chunk.content)
                
                # Check for sentence boundary to start TTS early
                if not tts_started and self._is_sentence_complete(sentence_buffer):
                    tts_started = True
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


# Global instance
brain = Brain()