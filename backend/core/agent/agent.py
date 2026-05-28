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
import asyncio
import json
import logging
import re
from typing import Any

import httpx

from backend.core.agent.context import ConversationContext
from backend.core.agent.verifier import verify as verify_tool_call
from backend.core.events import bus
from backend.core.tools import builtins  # noqa: F401 — populates REGISTRY
from backend.core.tools.registry import REGISTRY, call as call_tool, schemas_prompt
from backend.daemon.ui_events import VerificationEvent
from backend.server.config import settings

log = logging.getLogger(__name__)

MAX_ITER = 5

# ... (RESPONSE_ALIASES and _system_prompt unchanged)

async def _ollama_chat(messages: list[dict], model: str | None = None) -> str:
    """Talk to Ollama /api/chat in JSON-constrained mode."""
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model or settings.agent_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload)
    r.raise_for_status()
    body = r.json()
    msg = body.get("message", {})
    return (msg.get("content") or "").strip()


# ... (_parse, _normalize, _inline_referent unchanged)


async def run(text: str, context: ConversationContext) -> tuple[str, list[dict]]:
    """Run the agent loop asynchronously. Returns (spoken_text, [tool_call_records])."""
    resolved_text = _inline_referent(text, context)
    # Store the original phrasing in history so future turns see the actual
    # words the user said, not our rewritten form.
    context.add_user(text)

    history = context.render()
    # Replace the most recent user entry (which we just added) with the
    # referent-resolved version for the LLM only.
    history[-1] = {"role": "user", "content": resolved_text}
    messages = [{"role": "system", "content": _system_prompt()}, *history]

    tool_records: list[dict] = []

    for _iter in range(MAX_ITER):
        try:
            raw = await _ollama_chat(messages)
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

        # ── Verification Layer ───────────────────────────────────────
        valid_calls = []
        verification_errors = []
        is_multi_step = len(calls) > 1
        for c in calls:
            v_res = verify_tool_call(text, c, is_multi_step=is_multi_step)
            bus.publish(VerificationEvent(
                tool_name=c.get("name") or "unknown",
                is_valid=v_res.is_valid,
                error=v_res.error if not v_res.is_valid else None
            ))
            if v_res.is_valid:
                valid_calls.append(c)
            else:
                verification_errors.append(v_res.error)

        if verification_errors:
            log.warning(f"agent: verification failed: {verification_errors}")
            # Re-inject errors for the LLM to fix in the next iteration.
            error_msg = "Verification failed for some tool calls:\n" + \
                        "\n".join(f"- {e}" for e in verification_errors) + \
                        "\nPlease correct the tool names or arguments."
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": error_msg})
            continue  # retry next iteration
        # ─────────────────────────────────────────────────────────────

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

            result = await call_tool(name, args)
            tool_records.append({"name": name, "args": args, "result": result})

        last_batch = tool_records[-len(calls):]

        # Short-circuit: if EXACTLY ONE tool ran, succeeded, and produced a
        # user-ready `message`, speak it directly without asking gemma to
        # compose. Skips a second LLM round-trip (~10s) and eliminates the
        # "gemma re-calls the same tool" failure mode. Multi-tool chains
        # still fall through to composition.
        if len(last_batch) == 1:
            r = last_batch[0]
            res = r.get("result") or {}
            if res.get("status") == "success" and isinstance(res.get("message"), str) and res["message"].strip():
                spoken = res["message"].strip()
                context.add_assistant(spoken)
                return spoken, tool_records

        any_success = any(
            isinstance(r.get("result"), dict) and r["result"].get("status") == "success"
            for r in last_batch
        )
        if any_success:
            instruction = (
                "Multiple tools ran. Compose ONE final_response that summarizes "
                "all the results for the user. Reply with "
                "{\"final_response\": \"<short prose>\"}. Do NOT call any more tools."
            )
        else:
            instruction = (
                "Every tool failed. Either call a different tool listed in the schema, "
                "or reply with {\"final_response\": \"<short apology>\"}. "
                "Do NOT invent tool names — use only names from the schema."
            )

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": json.dumps({"tool_results": last_batch, "instruction": instruction}),
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
