import asyncio
import json
import logging
import uuid
from typing import List, Tuple

from backend.core.agent.context import ConversationContext
from backend.core.agents.guardian import GuardianAgent
from backend.core.agents.operator import OperatorAgent
from backend.core.agents.planner import PlannerAgent
from backend.core.healing import healer as self_healer
from backend.core.memory.episodic import summarizer as episodic_summarizer
from backend.core.memory.manager import memory as memory_manager

log = logging.getLogger(__name__)

MAX_ITER = 5

class CommanderAgent:
    """The central orchestrator of the specialized internal agents."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.guardian = GuardianAgent()
        self.operator = OperatorAgent()

    async def run(self, text: str, context: ConversationContext) -> Tuple[str, List[dict]]:
        # 1. Setup Request
        request_id = str(uuid.uuid4())[:8]
        context.add_user(text)
        history = context.render()
        
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
            valid_calls, errors = self.guardian.verify_plan(text, calls, request_id)

            if errors:
                log.warning(f"Commander: Guardian rejected parts of the plan: {errors}")
                # Feedback loop for fixing the plan
                last_error = errors[-1]
                path = self_healer.analyze(calls[0].get("name", "unknown"), last_error)
                instruction = self_healer.get_instruction(path, calls[0].get("name", "unknown"), last_error)
                
                history.append({"role": "assistant", "content": json.dumps({"tool_calls": calls})})
                history.append({"role": "user", "content": f"Correction needed: {instruction}"})
                continue

            # D. Operator Stage (Execution)
            batch_results = await self.operator.execute_batch(valid_calls, request_id)
            tool_records.extend(batch_results)

            # E. Assessment Stage
            # (Composition for final answer if needed)
            # This follows the previous logic: if one tool succeeded, speak its result.
            if len(batch_results) == 1:
                res = batch_results[0]["result"]
                if res.get("status") == "success" and res.get("message"):
                    spoken = res["message"]
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
