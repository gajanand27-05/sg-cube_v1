from typing import Any, List

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
            
            self._emit("executing_tool", tool=name)
            res = await call_tool(name, args, request_id=request_id)
            
            results.append({
                "name": name,
                "args": args,
                "result": res.model_dump() if hasattr(res, "model_dump") else res
            })
            
            self._emit("tool_finished", tool=name, status=res.status if hasattr(res, "status") else "done")

        return results
