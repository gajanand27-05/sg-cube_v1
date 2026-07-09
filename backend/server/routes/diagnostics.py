"""Phase G1-G2: Diagnostics & observability endpoints.

G1: Latency waterfall dashboard at /diagnostics
G2: Tool usage heatmap and Agent Inspector data
"""
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from backend.core.observability import engine as obs_engine
from backend.core.dogfooding import ledger as dogfooding_ledger
from backend.core.tools.registry import REGISTRY

log = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

# ── Tool usage tracking ──────────────────────────────────────────────
_tool_usage: dict[str, dict[str, Any]] = defaultdict(
    lambda: {"calls": 0, "successes": 0, "errors": 0, "total_latency_ms": 0, "avg_latency_ms": 0}
)


def record_tool_usage(name: str, success: bool, latency_ms: int) -> None:
    stats = _tool_usage[name]
    stats["calls"] += 1
    stats["total_latency_ms"] += latency_ms
    stats["avg_latency_ms"] = stats["total_latency_ms"] // stats["calls"]
    if success:
        stats["successes"] += 1
    else:
        stats["errors"] += 1
    # mirror into the persistent dogfooding ledger
    try:
        dogfooding_ledger.record_tool(success, latency_ms)
    except Exception:
        pass


@router.get("")
def get_diagnostics():
    """G1: Latency waterfall and system diagnostics."""
    metrics = obs_engine
    return {
        "system": {
            "uptime_sec": time.time() - _start_time,
            "total_tools": metrics._total_tools,
            "successful_tools": metrics._successful_tools,
            "success_rate": round(
                (metrics._successful_tools / metrics._total_tools * 100) if metrics._total_tools else 100, 1
            ),
            "tool_count": len(REGISTRY),
        },
        "latency": {
            "avg_response_sec": round(
                sum(metrics._latencies) / len(metrics._latencies), 3
            ) if metrics._latencies else 0,
            "latency_history": metrics._latencies[-50:],  # last 50
        },
        "hallucination": {
            "passed": metrics._hallucination_passed,
            "total": metrics._hallucination_total,
            "rate": round(
                (metrics._hallucination_passed / metrics._hallucination_total * 100)
                if metrics._hallucination_total else 100, 1
            ),
        },
        "memory_recall": {
            "avg_pct": round(
                sum(metrics._recall_scores) / len(metrics._recall_scores), 1
            ) if metrics._recall_scores else 100,
        },
        "dogfooding": dogfooding_ledger.snapshot(),
    }


@router.get("/dogfooding")
def get_dogfooding():
    """Lightweight counter summary from the persistent ledger."""
    return dogfooding_ledger.snapshot()


@router.get("/tools")
def get_tool_usage():
    """G2: Tool usage heatmap data."""
    sorted_tools = sorted(
        _tool_usage.items(),
        key=lambda x: x[1]["calls"],
        reverse=True,
    )
    return {
        "tools": [
            {
                "name": name,
                **stats,
                "success_rate": round(
                    (stats["successes"] / stats["calls"] * 100) if stats["calls"] else 100, 1
                ),
            }
            for name, stats in sorted_tools
        ]
    }


from fastapi import Body


@router.post("/emit-canvas")
def emit_canvas(widgets: list = Body(...)):
    """Phase 3 smoke-test endpoint: invoke render_canvas with the supplied
    widget list. Runs the same strict schema validator as any assistant
    call — an invalid payload is rejected here too, with no WS event
    emitted. Useful for exercising the frontend deterministically without
    depending on the LLM to pick the right tool call."""
    # Deferred import so this module doesn't drag Phase 3 into every request.
    from backend.core.tools.canvas import render_canvas

    result = render_canvas(widgets)
    return {
        "status": result.status.value,
        "message": result.message,
        "reason": result.reason,
        "data": result.data,
    }


@router.get("/preflight")
def get_preflight():
    """Phase 5C: end-to-end readiness snapshot.

    Runs every preflight check and returns the results as a JSON list plus
    a per-status summary. Would have caught the Phase 3 dead-WS-bridge
    bug at boot instead of at manual-test time — the ws_bridge check
    forces _setup_event_bridge() and verifies the flag flips.

    Callable at boot (log_preflight() in backend/core/preflight.py)
    AND on-demand via this endpoint. No billable API calls — LLM checks
    verify registration only, not generation.
    """
    from backend.core.preflight import run_preflight, summary
    checks = run_preflight()
    return {
        "summary": summary(checks),
        "checks": [
            {"name": c.name, "status": c.status.value, "message": c.message, "detail": c.detail}
            for c in checks
        ],
    }


@router.get("/latency")
def get_latency(n: int = 20):
    """Phase 4C: recent per-turn latency breakdowns.

    Returns the last `n` turns from the in-memory ring buffer. Each turn
    lists per-stage ms since VAD onset (or since text-turn start):

        wake → stt_done → orchestrator_route → context_ready →
        planner_first_token → first_tool_start → first_tool_end →
        first_audio_out → total

    Missing stages are omitted (a turn without tool calls won't have
    first_tool_start), so the response reports what actually happened
    rather than filling zeros. Reads from backend.core.latency.ledger()
    — see that module for the shape.
    """
    from backend.core.latency import ledger as latency_ledger

    turns = latency_ledger().recent(n=n)
    return {"turns": turns, "count": len(turns)}


@router.get("/inspect")
def agent_inspector():
    """Agent Inspector — current tool registry state with usage.

    `category` is the tool's source-module basename (e.g. "files",
    "web_reader", "games") so the dashboard can group tools by category
    without a hand-maintained mapping.
    """
    tools = []
    for name, tool_obj in REGISTRY.items():
        usage = _tool_usage.get(name, {})
        category = getattr(tool_obj.func, "__module__", "").rsplit(".", 1)[-1] or "other"
        tools.append({
            "name": name,
            "description": tool_obj.description,
            "security": tool_obj.security.value,
            "schema": tool_obj.schema,
            "usage": usage,
            "category": category,
        })
    return {"agents": {"planner": "gemma4", "operator": "tool-executor"}, "tools": tools}


_start_time = time.time()
