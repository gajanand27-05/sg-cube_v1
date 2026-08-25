import logging
from typing import Any, List, Tuple

from backend.core.agent.verifier import verify as verify_call
from backend.core.agents.base import BaseInternalAgent
from backend.core.tools.registry import REGISTRY, CapabilityTier, _resolve_name

log = logging.getLogger(__name__)


# How many side-effecting tool calls one utterance may produce before the
# whole plan needs confirming.
#
# The per-call tier gate is working as designed and is not what failed. Live:
#
#     [command] 'Notepad, chrome, firefox, vscode, spotify, whatsapp,
#                read the news, set a reminder,'
#     -> opened Notepad; opened Google Chrome; opened Firefox ESR;
#        opened vscode; opened spotify; opened WhatsApp; ... (tools: 7)
#
# Every one of those was a legitimately trusted `open_app` — prompting before
# opening a single app would make a voice assistant useless, and that decision
# stands (see project_permission_policy). What is missing is a gate on the
# FAN-OUT. One utterance asking for one action and one utterance turning into
# six are different events, and the second is far more likely to be a misheard
# or run-on transcript than a real request. The trailing comma above is the
# capture cutting the user off mid-sentence while they read a list aloud.
#
# 2 leaves ordinary compound requests ("open chrome and play music") alone.
MAX_UNCONFIRMED_SIDE_EFFECTS = 2


def _has_side_effects(call: dict) -> bool:
    """Does this call change anything? Unknown tools fail safe as YES.

    Mirrors the registry's own default: an untiered tool is DESTRUCTIVE, so a
    name we cannot resolve is counted rather than waved through.
    """
    name = call.get("name") or ""
    try:
        resolved = _resolve_name(name)
    except Exception:
        resolved = name
    tool_obj = REGISTRY.get(resolved) if resolved else None
    if tool_obj is None:
        return True
    tier = getattr(tool_obj, "tier", CapabilityTier.DESTRUCTIVE)
    if not isinstance(tier, CapabilityTier):
        return True
    return tier != CapabilityTier.READONLY


class GuardianAgent(BaseInternalAgent):
    """Specialized in safety, verification, and rules."""

    def __init__(self):
        super().__init__("Guardian")

    async def verify_plan(self, user_query: str, calls: List[dict], request_id: str, agent_context: Any = None) -> Tuple[List[dict], List[dict], List[str]]:
        self._emit("verifying", tool_count=len(calls))

        valid_calls = []
        pending_calls = []
        errors = []
        is_multi_step = len(calls) > 1

        # Counted over the whole plan before verifying any of it: the question
        # "is this turn doing too much" is about the turn, not about any one
        # call, and every individual call here may be perfectly fine.
        side_effects = sum(1 for c in calls if _has_side_effects(c))
        fan_out = side_effects > MAX_UNCONFIRMED_SIDE_EFFECTS
        if fan_out:
            log.warning(
                "Guardian: fan-out brake — %d side-effecting calls from one "
                "utterance %r; confirming before any of them run",
                side_effects, user_query,
            )
            self._emit("fan_out", tool_count=side_effects)

        for call in calls:
            res = await verify_call(user_query, call, is_multi_step=is_multi_step, request_id=request_id)
            if not res.is_valid:
                errors.append(res.error)
                self._emit("rejected", tool=call.get("name"), reason=res.error)
            elif res.needs_confirmation or (fan_out and _has_side_effects(call)):
                # Add metadata for the UI/Commander to know how to ask
                call["needs_confirmation"] = True
                call["is_critical"] = res.is_critical
                # Lets Commander phrase the prompt as "that's N actions"
                # rather than naming only the first one, which for six app
                # launches would ask "permission to open app" and hide the
                # scale — the exact thing being confirmed.
                call["fan_out"] = bool(fan_out and not res.needs_confirmation)
                pending_calls.append(call)
                self._emit("pending_confirmation", tool=call.get("name"), critical=res.is_critical)
            else:
                valid_calls.append(call)
                self._emit("verified", tool=call.get("name"))

        return valid_calls, pending_calls, errors
