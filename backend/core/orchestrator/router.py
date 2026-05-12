import logging
import time

from pydantic import BaseModel

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


def process_input(text: str, user_id: str) -> RouterResult:
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

    try:
        llm_hit = llm_resolve(text)
    except LLMResolveError:
        latency = int((time.perf_counter() - t0) * 1000)
        _log_to_db(user_id, text, None, "llm", "error", latency)
        raise

    latency = int((time.perf_counter() - t0) * 1000)
    cache_layer.set(norm, llm_hit)
    _log_to_db(user_id, text, llm_hit, "llm", "success", latency)
    return RouterResult(intent=llm_hit, source_layer="llm", latency_ms=latency)
