import json
import logging
import re
from typing import Any

from backend.ai_modules.llm import get_provider
from backend.ai_modules.llm.routing import TaskType
from backend.core.tools.registry import REGISTRY, CapabilityTier, SecurityLevel, _resolve_name
from backend.server.config import settings

log = logging.getLogger(__name__)

# ── Layer 1: Rule-Based Safety Definitions ──────────────────────────

# Deterministic blacklist of dangerous tokens
DANGEROUS_TOKENS = [
    "rm -rf", "shutdown", "format", "mkfs", "reg delete", "del /",
    "system32", "powershell -c", "cmd /c", "net user", "net localgroup"
]

# Shell injection patterns
INJECTION_PATTERN = re.compile(r"[;&|`$<>\{\}\[\]\\]")


class VerificationResult:
    def __init__(self, is_valid: bool, error: str = "", reasoning: str = "", needs_confirmation: bool = False, is_critical: bool = False):
        self.is_valid = is_valid
        self.error = error
        self.reasoning = reasoning
        self.needs_confirmation = needs_confirmation
        self.is_critical = is_critical


def _is_malicious(args: dict) -> str | None:
    """Scan all tool arguments for injection patterns or dangerous tokens."""
    for val in args.values():
        if not isinstance(val, str):
            continue
        v = val.lower()
        # 1. Blacklist check
        for token in DANGEROUS_TOKENS:
            if token in v:
                return f"Dangerous token detected: {token!r}"
        # 2. Injection check
        if INJECTION_PATTERN.search(val):
            return f"Potential injection pattern detected in argument: {val!r}"
    return None


async def _secondary_check(user_query: str, tool_name: str, tool_args: dict, reasoning: str) -> bool:
    """Ask a smaller, faster model (phi3) if this tool call makes sense."""
    llm = get_provider()
    prompt = f"""You are a safety and logic verifier for an AI Operating System.
User Query: "{user_query}"
Proposed Action: Call tool "{tool_name}" with arguments {json.dumps(tool_args)}
LLM Reasoning: "{reasoning}"

Is this action logically sound, safe, and directly relevant to the user's query?
Reply with a single JSON object: {{"verified": true}} or {{"verified": false, "reason": "..."}}"""
    try:
        response = await llm.generate(
            prompt,
            task=TaskType.CLASSIFICATION,
            json_mode=True,
            temperature=0.0,
        )
        res = json.loads(response)
        return bool(res.get("verified"))
    except Exception as e:
        log.warning(f"Secondary check failed: {e}")
        return False


async def verify(user_query: str, call: dict, is_multi_step: bool = False, request_id: str = "default") -> VerificationResult:
    """The SG_CUBE Verification Stack:
    1. Rule-based checks (Hallucination, Schema, Security, Injection)
    2. Confidence scoring (Routing Signal)
    3. Conditional verifier model (Only when needed)
    4. Action Approval Levels (SAFE, CAUTION, CRITICAL)
    """
    from backend.core.observability import engine as obs_engine
    
    name = (call.get("name") or "").strip()
    args = call.get("args") or {}
    reasoning = (call.get("reasoning") or "").strip()
    
    # ── 1. Rule-based Safety Checks ──────────────────────────────────
    
    # A. Hallucination Check
    resolved = _resolve_name(name, args)
    if not resolved:
        obs_engine.report_ai_quality(request_id, 0.0, f"Hallucinated tool: {name}")
        return VerificationResult(False, error=f"Tool {name!r} not found in registry.")

    obs_engine.report_ai_quality(request_id, 100.0, f"Tool {resolved} found")
    tool_obj = REGISTRY[resolved]

    # B. Malformed Check (Schema)
    params = tool_obj.schema.get("parameters", {})
    required = params.get("required", [])
    properties = params.get("properties", {})

    for req in required:
        if req not in args:
            obs_engine.report_context_quality(request_id, 0.0, f"Missing required arg: {req}")
            return VerificationResult(False, error=f"Missing required argument {req!r} for tool {resolved!r}.")

    # Simple type validation
    for key, val in args.items():
        if key in properties:
            expected_type = properties[key].get("type")
            valid_type = True
            if expected_type == "integer" and not isinstance(val, int): valid_type = False
            if expected_type == "number" and not isinstance(val, (int, float)): valid_type = False
            if expected_type == "string" and not isinstance(val, str): valid_type = False
            if expected_type == "boolean" and not isinstance(val, bool): valid_type = False
            
            if not valid_type:
                obs_engine.report_ai_quality(request_id, 50.0, f"Type mismatch for {key}")
                return VerificationResult(False, error=f"Argument {key!r} type mismatch.")

    obs_engine.report_context_quality(request_id, 100.0, "Schema valid")

    # C. Injection & Blacklist Check
    malicious_reason = _is_malicious(args)
    if malicious_reason:
        obs_engine.report_ai_quality(request_id, 0.0, f"Malicious input detected")
        return VerificationResult(False, error=malicious_reason)

    # ── 2. Confidence Scoring (Routing Signal) ───────────────────────
    
    try:
        conf_score = float(call.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf_score = 0.0

    obs_engine.report_ai_quality(request_id, conf_score * 100.0, "Self-reported confidence")

    # Tier: Phase 0 capability gate. Missing/unknown → DESTRUCTIVE (fail closed).
    tier = getattr(tool_obj, "tier", CapabilityTier.DESTRUCTIVE)
    if not isinstance(tier, CapabilityTier):
        tier = CapabilityTier.DESTRUCTIVE

    # ── 3. Conditional Verifier Model ────────────────────────────────
    # Trigger the secondary LLM check when the tool changes state, the LLM
    # is low-confidence, or the plan is multi-step. Keying off tier keeps
    # deep verification firing on state-changing calls even though the
    # legacy SecurityLevel column may not have been updated on new tools.
    needs_deep_verification = (
        conf_score < 0.80 or
        tier in (CapabilityTier.SYSTEM_WRITE, CapabilityTier.DESTRUCTIVE) or
        tool_obj.security in [SecurityLevel.CAUTION, SecurityLevel.CRITICAL] or
        is_multi_step
    )

    if needs_deep_verification:
        log.info(f"Triggering deep verification for {resolved!r} (conf={conf_score}, multi={is_multi_step}, tier={tier.value})")
        if not _secondary_check(user_query, resolved, args, reasoning):
            obs_engine.report_ai_quality(request_id, 20.0, "Secondary check failed")
            return VerificationResult(
                False,
                error="Action rejected by secondary verifier: logic or relevance mismatch."
            )
        obs_engine.report_ai_quality(request_id, 100.0, "Secondary check passed")

    # ── 4. Capability tier gate (Phase 0 Part B) ─────────────────────
    # Keys off tier, NOT SecurityLevel. This is the confirmation surface
    # the Guardian owns — sandbox.py's own SecurityLevel-based check is
    # a separate, deeper layer that fires at actual execution time.
    if tier == CapabilityTier.DESTRUCTIVE:
        obs_engine.report_ai_quality(request_id, 100.0, "Destructive tier — always confirm")
        # No flag can silence this — matches the Phase 0 contract.
        return VerificationResult(True, reasoning=reasoning, needs_confirmation=True, is_critical=True)

    if tier == CapabilityTier.SYSTEM_WRITE:
        if settings.auto_confirm_system_write:
            obs_engine.report_ai_quality(request_id, 100.0, "System-write auto-approved by config")
            return VerificationResult(True, reasoning=reasoning)
        obs_engine.report_ai_quality(request_id, 100.0, "System-write tier — confirm")
        return VerificationResult(True, reasoning=reasoning, needs_confirmation=True)

    # READONLY — pass through, no confirmation needed.
    return VerificationResult(True, reasoning=reasoning)
