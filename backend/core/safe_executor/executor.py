import logging
import time

from pydantic import BaseModel

from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor.command_whitelist import HANDLERS, is_target_dangerous

log = logging.getLogger(__name__)


class ExecutionResult(BaseModel):
    status: str
    intent: Intent
    message: str | None = None
    reason: str | None = None
    latency_ms: int


async def execute(intent: Intent) -> ExecutionResult:
    t0 = time.perf_counter()

    if is_target_dangerous(intent.target):
        return ExecutionResult(
            status="blocked",
            intent=intent,
            reason=f"dangerous target rejected: {intent.target!r}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    handler = HANDLERS.get(intent.action)
    if handler is None:
        return ExecutionResult(
            status="blocked",
            intent=intent,
            reason=f"unknown action: {intent.action!r}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    try:
        from backend.core.runtime import runtime
        # Rule-based intents use HANDLERS which take the Intent object.
        # We wrap them in the runtime for consistency, logging, and timeouts.
        res = await runtime.run_tool(intent.action, handler, {"intent": intent})
    except Exception as e:
        log.exception("executor handler crashed")
        return ExecutionResult(
            status="error",
            intent=intent,
            reason=str(e),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    return ExecutionResult(
        status=res.status,
        intent=intent,
        message=res.message,
        reason=res.reason,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
