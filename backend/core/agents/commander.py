import asyncio
import json
import logging
import uuid
from typing import List, Optional, Tuple, AsyncGenerator, Any

from backend.core.agent.context import ConversationContext
from backend.core.agents.guardian import GuardianAgent
from backend.core.agents.operator import OperatorAgent
from backend.core.agents.planner import PlannerAgent
from backend.core.context.builder import context_builder
from backend.core.context.types import RequestContext
from backend.core.healing import healer as self_healer
from backend.core.memory.episodic import summarizer as episodic_summarizer
from backend.core.memory.timeline import timeline

log = logging.getLogger(__name__)

MAX_ITER = 5


class CommanderChunk:
    """Streaming chunk from Commander."""
    def __init__(self, type: str, content: Any = None, metadata: dict = None):
        self.type = type
        self.content = content
        self.metadata = metadata or {}


class CommanderAgent:
    """The central orchestrator of the specialized internal agents."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.guardian = GuardianAgent()
        self.operator = OperatorAgent()
        self._current_task: Optional[asyncio.Task] = None

    def interrupt(self):
        """Stop the current reasoning/execution loop."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            log.info("Commander: Interrupted by user.")

    async def run(self, text: str, context: ConversationContext, user_id: str | None = None) -> Tuple[str, List[dict]]:
        """Non-streaming entry point — collects all chunks and returns final result."""
        spoken = ""
        tool_records = []
        async for chunk in self.run_stream(text, context, user_id):
            if chunk.type == "final_response":
                spoken = chunk.content
            elif chunk.type == "tool_end":
                tool_records.append(chunk.content)
        return spoken, tool_records

    async def run_stream(self, text: str, context: ConversationContext, user_id: str | None = None) -> AsyncGenerator[CommanderChunk, None]:
        """Streaming entry point — yields chunks as they're ready."""
        self._current_task = asyncio.current_task()
        try:
            async for chunk in self._run_loop_stream(text, context, user_id):
                yield chunk
        except asyncio.CancelledError:
            yield CommanderChunk("error", "Interrupted")
        finally:
            self._current_task = None

    async def _run_loop_stream(self, text: str, context: ConversationContext, user_id: str | None) -> AsyncGenerator[CommanderChunk, None]:
        # 1. Build unified context via ContextBuilder
        request = RequestContext(
            user_intent=text,
            user_id=user_id,
            session_id=context.session_id if hasattr(context, 'session_id') else None,
            request_id=str(uuid.uuid4())[:8],
            input_mode="voice",
        )
        agent_context = await context_builder.collect(request)

        # Update agent context with conversation history
        agent_context.recent_conversation = context.render()

        # 2. Setup Request
        request_id = agent_context.request_id
        context.add_user(text)
        history = agent_context.recent_conversation
        
        # Record user query in timeline
        timeline.record_event(content=f"User asked: \"{text}\"", source="user_query")
        
        tool_records: list[dict] = []

        for _iter in range(MAX_ITER):
            # A. Planner Stage (receives full AgentContext) - streaming
            async for chunk in self.planner.generate_plan_stream(text, history, agent_context):
                if chunk["type"] == "token":
                    yield CommanderChunk("token", chunk["content"], {"request_id": request_id})
                elif chunk["type"] == "final":
                    content = chunk["content"]
                    if isinstance(content, dict) and "final_response" in content:
                        yield CommanderChunk("final_response", content["final_response"])
                        context.add_assistant(content["final_response"])
                        asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                        return
                    # tool_calls
                    calls = content if isinstance(content, list) else content.get("tool_calls", [content])
                    # B. Guardian Stage (Verification)
                    valid_calls, pending_calls, errors = await self.guardian.verify_plan(text, calls, request_id, agent_context)

                    if errors:
                        log.warning(f"Commander: Guardian rejected parts of the plan: {errors}")
                        last_error = errors[-1]
                        path = self_healer.analyze(calls[0].get("name", "unknown"), last_error)
                        instruction = self_healer.get_instruction(path, calls[0].get("name", "unknown"), last_error)
                        
                        history.append({"role": "assistant", "content": json.dumps({"tool_calls": calls})})
                        history.append({"role": "user", "content": f"Correction needed: {instruction}"})
                        continue

                    if pending_calls:
                        first_pending = pending_calls[0]
                        tool_name = first_pending.get("name", "action").replace("_", " ")
                        is_critical = first_pending.get("is_critical", False)
                        
                        if is_critical:
                            spoken = f"⚠️ CRITICAL ACTION: I need your explicit permission to {tool_name}. This is a high-risk operation. Should I proceed?"
                        else:
                            spoken = f"I need your permission to {tool_name}. Should I proceed?"
                        
                        context.add_assistant(spoken)
                        yield CommanderChunk("final_response", spoken)
                        return

                    # C. Operator Stage (Execution)
                    batch_results = await self.operator.execute_batch(valid_calls, request_id)
                    tool_records.extend(batch_results)

                    # Record successful tool executions in timeline
                    for res_wrapper in batch_results:
                        res = res_wrapper.get("result")
                        status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                        if status == "success":
                            tool_name = res_wrapper.get("tool", "unknown tool").replace("_", " ")
                            msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else "success")
                            timeline.record_event(
                                content=f"Executed {tool_name}: {msg}",
                                source="execution"
                            )

                    # Yield tool results
                    for res in batch_results:
                        yield CommanderChunk("tool_end", res)

                    # D. Assessment Stage
                    if len(batch_results) == 1:
                        res = batch_results[0]["result"]
                        status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                        msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else None)
                        
                        if status == "success" and msg:
                            spoken = msg
                            context.add_assistant(spoken)
                            asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                            yield CommanderChunk("final_response", spoken)
                            return

                    # Multi-tool summary request
                    history.append({"role": "assistant", "content": json.dumps({"tool_calls": valid_calls})})
                    history.append({
                        "role": "user", 
                        "content": json.dumps({"tool_results": batch_results, "instruction": "Summarize results for the user."})
                    })

        yield CommanderChunk("final_response", "I tried a few steps but couldn't finish that.")


# Global instance
commander = CommanderAgent()
