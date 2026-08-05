from typing import Any, List

import time

from backend.core.agents.base import BaseInternalAgent
from backend.core.tools.registry import call as call_tool


class OperatorAgent(BaseInternalAgent):
    """Specialized in tool execution and runtime interaction."""

    def __init__(self):
        super().__init__("Operator")

    async def execute_batch(self, calls: List[dict], request_id: str) -> List[dict]:
        self._emit("executing", count=len(calls))
        results = []

        for c in calls:
            name = (c.get("name") or "").strip()
            args = c.get("args") or {}
            t0 = time.perf_counter()

            self._emit("executing_tool", tool=name)
            res = await call_tool(name, args, request_id=request_id)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            # Publish to ObservabilityEngine so ConfidenceEvent fires.
            # The engine aggregates per-call stats and publishes ConfidenceEvent.
            try:
                from backend.core.observability import engine as obs
                obs.report_tool_quality(request_id, res.confidence, f"{res.status}: {name}")
                obs.report_latency(request_id, latency_ms)
            except Exception:
                pass

            results.append({
                "name": name,
                "args": args,
                "result": res.model_dump() if hasattr(res, "model_dump") else res
            })

            self._emit("tool_finished", tool=name, status=res.status if hasattr(res, "status") else "done")

        return results
