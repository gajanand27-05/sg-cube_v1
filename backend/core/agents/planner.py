import asyncio
import json
from typing import Any, List

import httpx

from backend.core.agents.base import BaseInternalAgent, TokenStreamEvent
from backend.core.events import bus
from backend.core.tools.registry import schemas_prompt
from backend.daemon.ui_events import AgentThinkingEvent
from backend.server.config import settings


class PlannerAgent(BaseInternalAgent):
    """Specialized in strategic breakdown and tool selection."""

    def __init__(self):
        super().__init__("Planner")

    async def generate_plan(self, user_query: str, history: list[dict], memory_context: str) -> list[dict]:
        self._emit("planning", query=user_query)
        bus.publish(AgentThinkingEvent(self.name, True))

        prompt = self._build_prompt(memory_context)
        messages = [{"role": "system", "content": prompt}, *history]

        url = f"{settings.ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": settings.agent_model,
            "messages": messages,
            "stream": True,  # Enable streaming
            "format": "json",
            "options": {"temperature": 0.2},
        }

        full_content = ""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line: continue
                        body = json.loads(line)
                        token = body.get("message", {}).get("content", "")
                        full_content += token
                        
                        # Emit streaming event
                        bus.publish(TokenStreamEvent(self.name, token, full_content))
                        
                        if body.get("done"): break

            parsed = json.loads(full_content)
            # Basic normalization for tool calls
            calls = parsed.get("tool_calls") or parsed.get("toolCalls") or []
            if not isinstance(calls, list):
                calls = [parsed] if "name" in parsed else []

            self._emit("plan_ready", tool_count=len(calls))
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
