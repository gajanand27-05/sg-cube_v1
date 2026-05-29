from typing import List, Tuple

from backend.core.agent.verifier import verify as verify_call
from backend.core.agents.base import BaseInternalAgent


class GuardianAgent(BaseInternalAgent):
    """Specialized in safety, verification, and rules."""

    def __init__(self):
        super().__init__("Guardian")

    def verify_plan(self, user_query: str, calls: List[dict], request_id: str) -> Tuple[List[dict], List[str]]:
        self._emit("verifying", tool_count=len(calls))
        
        valid_calls = []
        errors = []
        is_multi_step = len(calls) > 1

        for call in calls:
            res = verify_call(user_query, call, is_multi_step=is_multi_step, request_id=request_id)
            if res.is_valid:
                valid_calls.append(call)
                self._emit("verified", tool=call.get("name"))
            else:
                errors.append(res.error)
                self._emit("rejected", tool=call.get("name"), reason=res.error)

        return valid_calls, errors
