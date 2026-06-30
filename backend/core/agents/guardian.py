from typing import List, Tuple

from backend.core.agent.verifier import verify as verify_call
from backend.core.agents.base import BaseInternalAgent


class GuardianAgent(BaseInternalAgent):
    """Specialized in safety, verification, and rules."""

    def __init__(self):
        super().__init__("Guardian")

    async def verify_plan(self, user_query: str, calls: List[dict], request_id: str) -> Tuple[List[dict], List[dict], List[str]]:
        self._emit("verifying", tool_count=len(calls))

        valid_calls = []
        pending_calls = []
        errors = []
        is_multi_step = len(calls) > 1

        for call in calls:
            res = await verify_call(user_query, call, is_multi_step=is_multi_step, request_id=request_id)
            if not res.is_valid:
                errors.append(res.error)
                self._emit("rejected", tool=call.get("name"), reason=res.error)
            elif res.needs_confirmation:
                # Add metadata for the UI/Commander to know how to ask
                call["needs_confirmation"] = True
                call["is_critical"] = res.is_critical
                pending_calls.append(call)
                self._emit("pending_confirmation", tool=call.get("name"), critical=res.is_critical)
            else:
                valid_calls.append(call)
                self._emit("verified", tool=call.get("name"))

        return valid_calls, pending_calls, errors
