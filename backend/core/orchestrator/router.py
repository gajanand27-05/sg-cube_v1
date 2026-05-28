import logging
import time

from pydantic import BaseModel

from backend.core.agent import agent as agent_module
from backend.core.agent.context import get_context
from backend.core.orchestrator import cache_layer, rule_engine
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.llm_layer import resolve as llm_resolve
from backend.core.orchestrator.normalize import normalize
from backend.database.supabase_client import get_service_client

log = logging.getLogger(__name__)


class RouterResult(BaseModel):
    intent: Intent
    source_layer: str
    latency_ms: int
    status: str = "success"


def _log_to_db(
    user_id: str,
    input_text: str,
    intent: Intent | None,
    source_layer: str,
    status: str,
    latency_ms: int,
) -> None:
    try:
        get_service_client().table("command_logs").insert(
            {
                "user_id": user_id,
                "input_text": input_text,
                "resolved_action": intent.model_dump() if intent else None,
                "source_layer": source_layer,
                "status": status,
                "latency_ms": latency_ms,
            }
        ).execute()
    except Exception as e:
        log.warning("command_logs insert failed: %s", e)


async def process_input(text: str, user_id: str) -> RouterResult:
    t0 = time.perf_counter()
    norm = normalize(text)
    if not norm:
        return RouterResult(
            intent=Intent(action="unknown", target=""),
            source_layer="rule",
            latency_ms=0,
            status="error",
        )

    cached = cache_layer.get(norm)
    if cached is not None:
        latency = int((time.perf_counter() - t0) * 1000)
        _log_to_db(user_id, text, cached, "cache", "success", latency)
        return RouterResult(intent=cached, source_layer="cache", latency_ms=latency)

    rule_hit = rule_engine.match(norm)
    if rule_hit is not None:
        latency = int((time.perf_counter() - t0) * 1000)
        cache_layer.set(norm, rule_hit)
        _log_to_db(user_id, text, rule_hit, "rule", "success", latency)
        return RouterResult(intent=rule_hit, source_layer="rule", latency_ms=latency)

    # ── Phase 11a: agent path ────────────────────────────────────────
    # Cache + rules miss → invoke the tool-calling agent (gemma4). It can
    # chain tool calls, answer questions directly, and use recent
    # conversation context for follow-ups.
    try:
        spoken, tool_records = await agent_module.run(text, get_context())
    except Exception as e:
        log.exception("agent run failed: %s", e)
        latency = int((time.perf_counter() - t0) * 1000)
        _log_to_db(user_id, text, None, "llm", "error", latency)
        raise LLMResolveError(str(e)) from e

    latency = int((time.perf_counter() - t0) * 1000)
    synthetic = Intent(
        action="agent_complete",
        target=text,
        args={"spoken": spoken, "tool_records": tool_records},
    )
    # NOT cached: agent responses are context-dependent (e.g. "louder" means
    # different things at different times).
    _log_to_db(user_id, text, synthetic, "llm", "success", latency)
    return RouterResult(intent=synthetic, source_layer="llm", latency_ms=latency)
