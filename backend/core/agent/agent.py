"""Tool-calling agent loop.

Talks to a larger Ollama model (gemma4 by default) in JSON mode. Each turn:

    1. Send: system prompt + tools + recent context + new user message + any
       tool results from this turn so far.
    2. LLM returns ONE of:
         {"tool_calls": [{"name": "...", "args": {...}}, ...]}
         {"final_response": "spoken text"}
    3. If tool_calls: execute, append results, loop.
       If final_response: stop and return.
    4. Hard cap: MAX_ITER iterations to prevent runaway.

Importing this module pulls in builtins.py which registers the initial tool
set into REGISTRY.
"""
import json
import logging
from typing import Any

import httpx

from backend.core.agent.context import ConversationContext
from backend.core.tools import builtins  # noqa: F401 — populates REGISTRY
from backend.core.tools.registry import REGISTRY, call as call_tool, schemas_prompt
from backend.server.config import settings

log = logging.getLogger(__name__)

MAX_ITER = 5


def _system_prompt() -> str:
    return f"""You are SG_CUBE, a local AI Operating System running on the user's Windows machine.
You answer voice commands by either calling tools or replying directly.

Available tools (JSON schema):
{schemas_prompt()}

PROTOCOL — every reply MUST be a single JSON object with EXACTLY ONE of these shapes:

  TOOL CALL (when an action is needed):
    {{"tool_calls": [{{"name": "<tool_name>", "args": {{"<param>": "<value>"}}}}]}}

  FINAL ANSWER (when no action is needed, or after seeing tool results, or for a question):
    {{"final_response": "<short sentence to speak aloud>"}}

RULES:
- Output ONLY the JSON object. No markdown, no commentary, no code fences.
- "tool_calls" can include multiple tools if the user asked for multiple actions
  (e.g. "open chrome and play music" -> [open_app(chrome), play_youtube(music)]).
- After a tool runs, you'll see its result. Use it to compose a final_response.
- final_response should be one short sentence — it's read aloud, not displayed.
- For factual/math/general questions ("what's the capital of Brazil",
  "what's 240 dollars in rupees"), reply with final_response directly. Do not
  call a tool — you know the answer.
- For "play X" / "play X on youtube" -> call play_youtube.
- For "search X" / "google X" -> call search_web.
- For "open X" where X is an app -> call open_app.
- For "open X" where X is a website -> call open_url.
- Conversation history is provided. Resolve follow-ups ("louder", "next song",
  "and then close it") relative to the most recent commands.
"""


def _ollama_chat(messages: list[dict], model: str | None = None) -> str:
    """Talk to Ollama /api/chat in JSON-constrained mode."""
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model or settings.agent_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, json=payload)
    r.raise_for_status()
    body = r.json()
    msg = body.get("message", {})
    return (msg.get("content") or "").strip()


def _parse(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("agent: bad JSON from LLM: %s; raw=%r", e, raw[:200])
        return {"final_response": "Sorry, I got confused."}


def run(text: str, context: ConversationContext) -> tuple[str, list[dict]]:
    """Run the agent loop. Returns (spoken_text, [tool_call_records])."""
    context.add_user(text)

    history = context.render()
    messages = [{"role": "system", "content": _system_prompt()}, *history]

    tool_records: list[dict] = []

    for _iter in range(MAX_ITER):
        try:
            raw = _ollama_chat(messages)
        except Exception as e:
            log.exception("agent: ollama call failed")
            spoken = "Sorry, I couldn't reach my reasoning model."
            context.add_assistant(spoken)
            return spoken, tool_records

        parsed = _parse(raw)

        if "final_response" in parsed:
            spoken = str(parsed["final_response"]).strip() or "Done."
            context.add_assistant(spoken)
            return spoken, tool_records

        calls = parsed.get("tool_calls") or []
        if not calls:
            # The model returned neither — give up gracefully.
            spoken = "Sorry, I didn't know what to do with that."
            context.add_assistant(spoken)
            return spoken, tool_records

        # Execute each tool call and append results back into the conversation
        # for the model to reason about on the next iteration.
        for c in calls:
            name = (c.get("name") or "").strip()
            args = c.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            result = call_tool(name, args)
            tool_records.append({"name": name, "args": args, "result": result})

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {"tool_results": tool_records[-len(calls):]}
                ),
            }
        )

    spoken = "I tried a few steps but couldn't finish that."
    context.add_assistant(spoken)
    return spoken, tool_records
