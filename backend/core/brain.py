"""Brain — transport-agnostic orchestrator for the intelligence pipeline.

All inputs (voice, text, proactive, MCP, REST) funnel through Brain.run().
"""
import uuid
import time
from dataclasses import dataclass, field
from typing import Any

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
class BrainResponse:
    """Output from the brain."""
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
        """Main entry point — runs the full intelligence pipeline."""
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

        # Create conversation context for Commander
        conversation = ConversationContext()
        
        # Run Commander pipeline (Planner → Guardian → Operator → Healer)
        spoken, tool_records = await self.commander.run(
            request.input_text, 
            conversation,
            user_id=request.user_id
        )

        # Build response
        latency_ms = int((time.perf_counter() - t0) * 1000)

        tool_calls = []
        for record in tool_records:
            tool_calls.append(ToolCall(
                name=record.get("name", "unknown"),
                args=record.get("args", {}),
                result=record.get("result"),
                latency_ms=record.get("result", {}).get("latency_ms", 0) if isinstance(record.get("result"), dict) else 0,
                status=getattr(record.get("result"), "status", record.get("result", {}).get("status", "success")) if record.get("result") else "error"
            ))

        execution_trace = [
            {"stage": "context_build", "latency_ms": 0},
            {"stage": "planner", "latency_ms": 0},
            {"stage": "guardian", "latency_ms": 0},
            {"stage": "operator", "latency_ms": sum(tc.latency_ms for tc in tool_calls)},
            {"stage": "tts", "latency_ms": 0},
        ]

        return BrainResponse(
            spoken_text=spoken,
            intent={"action": "agent_complete", "target": request.input_text, "args": {}},
            tool_calls=tool_calls,
            execution_trace=execution_trace,
            latency_ms=latency_ms,
            metadata={
                "request_id": request_id,
                "input_mode": request.input_mode,
                "context_keys": list(agent_context.__dict__.keys()),
            }
        )


# Global instance
brain = Brain()