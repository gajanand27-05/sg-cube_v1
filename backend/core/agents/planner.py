import json
from typing import Any

from backend.ai_modules.llm import get_provider
from backend.core.agents.base import BaseInternalAgent, TokenStreamEvent
from backend.core.events import bus
from backend.core.tools.registry import schemas_prompt
from backend.daemon.ui_events import AgentThinkingEvent
from backend.ai_modules.llm.routing import TaskType
from backend.core.context.types import AgentContext


class PlannerAgent(BaseInternalAgent):
    """Specialized in strategic breakdown and tool selection."""

    def __init__(self):
        super().__init__("Planner")

    async def generate_plan(self, user_query: str, history: list[dict], context: AgentContext) -> list[dict]:
        self._emit("planning", query=user_query)
        bus.publish(AgentThinkingEvent(self.name, True))

        prompt = self._build_prompt(context)
        messages = [{"role": "system", "content": prompt}, *history]

        full_content = ""
        try:
            llm = get_provider()
            async for chunk in llm.chat_stream(messages, task=TaskType.REASONING, temperature=0.2):
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

    def _build_prompt(self, context: AgentContext) -> str:
        from backend.core.safe_executor.command_whitelist import _get_chrome_profiles
        profiles = _get_chrome_profiles()
        profile_hint = ""
        if profiles:
            names = ", ".join(sorted(profiles))
            profile_hint = f"\nChrome profiles available: {names}\nIf the user asks about 'my account' or a Chrome profile, use the matching profile name from this list.\n"

        # Build capability list from context
        caps = "\n".join([f"- {c.name}: {c.description}" for c in context.capabilities[:50]])
        
        # Build memory context string
        memory_parts = []
        if context.recent_conversation:
            memory_parts.append("Recent conversation:\n" + "\n".join(str(m) for m in context.recent_conversation[-5:]))
        if context.long_term_memory:
            memory_parts.append("Relevant facts:\n" + "\n".join(f"- {m.content}" for m in context.long_term_memory))
        if context.recent_events:
            memory_parts.append("Recent activity:\n" + "\n".join(f"- {e.content}" for e in context.recent_events[:5]))
        memory_context = "\n\n".join(memory_parts) if memory_parts else "No relevant memory."

        return f"""You are the PLANNER Agent for SG_CUBE.
Available capabilities:
{caps}
{profile_hint}
{memory_context}

Output ONLY a JSON object with:
{{"tool_calls": [{{"name": "capability", "args": {{...}}, "confidence": 0.0-1.0, "reasoning": "..."}}]}}
If no action is needed, return {{"final_response": "..."}}.
"""
