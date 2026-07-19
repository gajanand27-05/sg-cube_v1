import logging
import time

from pydantic import BaseModel

from backend.core.agents.commander import commander as agent_module
from backend.core.agent.context import get_context
from backend.core.events import Priority, get_bus
from backend.core.orchestrator import cache_layer, rule_engine
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.llm_layer import resolve as llm_resolve
from backend.core.orchestrator.normalize import normalize, normalize_for_rules
from backend.daemon.ui_events import IntentResolved
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


def _publish_resolved(intent: Intent, source_layer: str) -> None:
    """Announce a resolved intent on the bus.

    Mirrors _log_to_db: called at each successful exit of process_input so
    the UI's router-tier strip can count cache/rule/llm hits. Never raises —
    a telemetry failure must not break command resolution.
    """
    try:
        get_bus().publish(
            IntentResolved(
                action=intent.action,
                target=intent.target,
                source_layer=source_layer,
            ),
            priority=Priority.NORMAL,
        )
    except Exception as e:
        log.warning("IntentResolved publish failed: %s", e)


async def process_input(text: str, user_id: str) -> RouterResult:
    t0 = time.perf_counter()
    # Two normalizers, two jobs. The cache key drops punctuation so near-miss
    # phrasings collapse onto one entry; the rule engine needs punctuation
    # intact or its arithmetic and URL patterns can never match.
    cache_key = normalize(text)
    rule_input = normalize_for_rules(text)
    if not cache_key:
        return RouterResult(
            intent=Intent(action="unknown", target=""),
            source_layer="rule",
            latency_ms=0,
            status="error",
        )

    cached = cache_layer.get_fuzzy(cache_key)
    if cached is not None:
        latency = int((time.perf_counter() - t0) * 1000)
        _log_to_db(user_id, text, cached, "cache", "success", latency)
        _publish_resolved(cached, "cache")
        return RouterResult(intent=cached, source_layer="cache", latency_ms=latency)

    rule_hit = rule_engine.match(rule_input)
    if rule_hit is not None:
        latency = int((time.perf_counter() - t0) * 1000)
        cache_layer.set(cache_key, rule_hit)
        _log_to_db(user_id, text, rule_hit, "rule", "success", latency)
        _publish_resolved(rule_hit, "rule")
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
    _publish_resolved(synthetic, "llm")
    return RouterResult(intent=synthetic, source_layer="llm", latency_ms=latency)
