import json

from backend.ai_modules.llm import openrouter_client
from backend.core.agents.base import BaseInternalAgent, TokenStreamEvent
from backend.core.events import bus
from backend.core.tools.registry import schemas_prompt
from backend.daemon.ui_events import AgentThinkingEvent


class PlannerAgent(BaseInternalAgent):
    """Specialized in strategic breakdown and tool selection."""

    def __init__(self):
        super().__init__("Planner")

    async def generate_plan(self, user_query: str, history: list[dict], memory_context: str) -> list[dict]:
        self._emit("planning", query=user_query)
        bus.publish(AgentThinkingEvent(self.name, True))

        prompt = self._build_prompt(memory_context)
        messages = [{"role": "system", "content": prompt}, *history]

        full_content = ""
        try:
            async for chunk in openrouter_client.chat_stream(messages, json_mode=True, temperature=0.2):
                token = chunk["token"]
                full_content += token
                bus.publish(TokenStreamEvent(self.name, token, full_content))

            parsed = json.loads(full_content)

            if "final_response" in parsed:
                return parsed

            calls = parsed.get("tool_calls") or parsed.get("toolCalls") or []
            if not isinstance(calls, list):
                calls = [parsed] if "name" in parsed else []

            steps = [c.get("reasoning", c.get("name")) for c in calls]
            self._emit("plan_ready", tool_count=len(calls), steps=steps)
            return calls
        except Exception as e:
            self._emit("error", detail=str(e))
            raise
        finally:
            bus.publish(AgentThinkingEvent(self.name, False))

    def _build_prompt(self, memory_context: str) -> str:
        return f"""You are the PLANNER Agent for SG_CUBE.
Available tools:
{schemas_prompt()}

{memory_context}

Output ONLY a JSON object with:
{{"tool_calls": [{{"name": "tool", "args": {{...}}, "confidence": 0.0-1.0, "reasoning": "..."}}]}}
If no action is needed, return {{"final_response": "..."}}.
"""
