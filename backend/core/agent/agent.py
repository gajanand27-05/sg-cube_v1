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

# Models often hallucinate a "speak" / "say" / "final_response" tool when
# they really mean "produce the final response". Treat any of these as
# terminal — extract the text and return immediately.
RESPONSE_ALIASES = {
    "respond", "speak", "say", "answer", "reply", "tell_user", "tell",
    "final_response", "final_answer", "result", "output",
}


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
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("agent: bad JSON from LLM: %s; raw=%r", e, raw[:200])
        return {"final_response": "Sorry, I got confused."}
    return _normalize(parsed)


def _normalize(parsed: Any) -> dict[str, Any]:
    """Different models like different tool-call JSON shapes. Coerce them all
    into one of: {"tool_calls": [{"name": ..., "args": ...}, ...]} or
    {"final_response": "..."}."""
    if not isinstance(parsed, dict):
        return {"final_response": "Sorry, I got confused."}

    # final_response synonyms
    for key in ("final_response", "final_answer", "response", "answer", "reply"):
        v = parsed.get(key)
        if isinstance(v, str) and v.strip():
            return {"final_response": v.strip()}

    def _extract_call(c: dict) -> dict | None:
        if not isinstance(c, dict):
            return None
        name = c.get("name") or c.get("tool_name") or c.get("function") or c.get("function_name")
        if not name:
            return None
        args = c.get("args") or c.get("arguments") or c.get("parameters") or c.get("params") or {}
        if not isinstance(args, dict):
            args = {}
        return {"name": str(name).strip(), "args": args}

    # Multiple tool calls in a list
    tc = parsed.get("tool_calls") or parsed.get("toolCalls") or parsed.get("calls")
    if isinstance(tc, list):
        calls = [c for c in (_extract_call(x) for x in tc) if c and c["name"]]
        if calls:
            return {"tool_calls": calls}

    # Single tool call without the array wrapper
    if isinstance(tc, dict):
        c = _extract_call(tc)
        if c and c["name"]:
            return {"tool_calls": [c]}

    # Top-level single tool call
    c = _extract_call(parsed)
    if c and c["name"]:
        return {"tool_calls": [c]}

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

        # Execute each tool call. If any call is a "respond" / "speak" /
        # "say" alias, treat its text as the final answer and exit.
        for c in calls:
            name = (c.get("name") or "").strip()
            args = c.get("args") or {}
            if not isinstance(args, dict):
                args = {}

            if name.lower() in RESPONSE_ALIASES:
                spoken = (
                    args.get("text")
                    or args.get("message")
                    or args.get("response")
                    or args.get("content")
                    or "Done."
                )
                spoken = str(spoken).strip() or "Done."
                tool_records.append({"name": name, "args": args, "result": {"status": "success"}})
                context.add_assistant(spoken)
                return spoken, tool_records

            result = call_tool(name, args)
            tool_records.append({"name": name, "args": args, "result": result})

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "tool_results": tool_records[-len(calls):],
                        "instruction": "Now reply with {\"final_response\": \"<short sentence to speak>\"} based on the tool result above. Do not call the same tool again.",
                    }
                ),
            }
        )

    # MAX_ITER exhausted. If we managed to run at least one successful tool,
    # speak its message rather than giving up — gemma did the work, it just
    # couldn't formulate a clean final_response.
    last_success = next(
        (
            r
            for r in reversed(tool_records)
            if isinstance(r.get("result"), dict) and r["result"].get("status") == "success"
        ),
        None,
    )
    if last_success and last_success["result"].get("message"):
        spoken = str(last_success["result"]["message"])
    else:
        spoken = "I tried a few steps but couldn't finish that."
    context.add_assistant(spoken)
    return spoken, tool_records
