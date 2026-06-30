import asyncio
import json
import logging
import uuid
from typing import List, Optional, Tuple

from backend.core.agent.context import ConversationContext
from backend.core.agents.guardian import GuardianAgent
from backend.core.agents.operator import OperatorAgent
from backend.core.agents.planner import PlannerAgent
from backend.core.healing import healer as self_healer
from backend.core.memory.episodic import summarizer as episodic_summarizer
from backend.core.memory.manager import memory as memory_manager
from backend.core.memory.timeline import timeline

log = logging.getLogger(__name__)

MAX_ITER = 5

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

    async def run(self, text: str, context: ConversationContext) -> Tuple[str, List[dict]]:
        self._current_task = asyncio.current_task()
        try:
            return await self._run_loop(text, context)
        except asyncio.CancelledError:
            return "Interrupted.", []
        finally:
            self._current_task = None

    async def _run_loop(self, text: str, context: ConversationContext) -> Tuple[str, List[dict]]:
        # 1. Setup Request
        request_id = str(uuid.uuid4())[:8]
        context.add_user(text)
        history = context.render()
        
        # Record user query in timeline
        timeline.record_event(content=f"User asked: \"{text}\"", source="user_query")
        
        tool_records: list[dict] = []

        for _iter in range(MAX_ITER):
            # A. Scholar Stage (Memory Injection)
            mem_context = memory_manager.get_relevant_context(text)
            
            # B. Planner Stage
            calls = await self.planner.generate_plan(text, history, mem_context)
            
            # Check for final response from Planner
            if isinstance(calls, dict) and "final_response" in calls:
                spoken = calls["final_response"]
                context.add_assistant(spoken)
                asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                memory_manager.wm.clear()
                return spoken, tool_records

            if not calls:
                spoken = "I'm not sure how to help with that."
                context.add_assistant(spoken)
                return spoken, tool_records

            # C. Guardian Stage (Verification)
            valid_calls, pending_calls, errors = await self.guardian.verify_plan(text, calls, request_id)

            if errors:
                log.warning(f"Commander: Guardian rejected parts of the plan: {errors}")
                # Feedback loop for fixing the plan
                last_error = errors[-1]
                path = self_healer.analyze(calls[0].get("name", "unknown"), last_error)
                instruction = self_healer.get_instruction(path, calls[0].get("name", "unknown"), last_error)
                
                history.append({"role": "assistant", "content": json.dumps({"tool_calls": calls})})
                history.append({"role": "user", "content": f"Correction needed: {instruction}"})
                continue

            if pending_calls:
                # Handle Action Approval Levels
                first_pending = pending_calls[0]
                tool_name = first_pending.get("name", "action").replace("_", " ")
                is_critical = first_pending.get("is_critical", False)
                
                if is_critical:
                    spoken = f"⚠️ CRITICAL ACTION: I need your explicit permission to {tool_name}. This is a high-risk operation. Should I proceed?"
                else:
                    spoken = f"I need your permission to {tool_name}. Should I proceed?"
                
                context.add_assistant(spoken)
                # In a real implementation, we would store the pending plan 
                # in session state to resume when the user says "yes".
                # For now, we just inform the user.
                return spoken, tool_records

            # D. Operator Stage (Execution)
            batch_results = await self.operator.execute_batch(valid_calls, request_id)
            tool_records.extend(batch_results)

            # Record successful tool executions in timeline
            for res_wrapper in batch_results:
                res = res_wrapper.get("result")
                # ToolResult or legacy dict
                status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                if status == "success":
                    tool_name = res_wrapper.get("tool", "unknown tool").replace("_", " ")
                    msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else "success")
                    timeline.record_event(
                        content=f"Executed {tool_name}: {msg}",
                        source="execution"
                    )

            # E. Assessment Stage
            # (Composition for final answer if needed)
            # This follows the previous logic: if one tool succeeded, speak its result.
            if len(batch_results) == 1:
                res = batch_results[0]["result"]
                status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else None)
                
                if status == "success" and msg:
                    spoken = msg
                    context.add_assistant(spoken)
                    asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                    return spoken, tool_records

            # Multi-tool summary request
            history.append({"role": "assistant", "content": json.dumps({"tool_calls": valid_calls})})
            history.append({
                "role": "user", 
                "content": json.dumps({"tool_results": batch_results, "instruction": "Summarize results for the user."})
            })

        return "I tried a few steps but couldn't finish that.", tool_records


# Global instance
commander = CommanderAgent()
