import json
import logging
from typing import Any

import httpx

from backend.core.tools.registry import REGISTRY, SecurityLevel, _resolve_name
from backend.server.config import settings

log = logging.getLogger(__name__)


class VerificationResult:
    def __init__(self, is_valid: bool, error: str = "", reasoning: str = ""):
        self.is_valid = is_valid
        self.error = error
        self.reasoning = reasoning


def _secondary_check(user_query: str, tool_name: str, tool_args: dict, reasoning: str) -> bool:
    """Ask a smaller, faster model (phi3) if this tool call makes sense."""
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    prompt = f"""You are a safety and logic verifier for an AI Operating System.
User Query: "{user_query}"
Proposed Action: Call tool "{tool_name}" with arguments {json.dumps(tool_args)}
LLM Reasoning: "{reasoning}"

Is this action logically sound, safe, and directly relevant to the user's query?
Reply with a single JSON object: {{"verified": true}} or {{"verified": false, "reason": "..."}}
"""
    payload = {
        "model": settings.ollama_model,  # phi3
        "messages": [{"role": "system", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, json=payload)
        r.raise_for_status()
        body = r.json()
        content = (body.get("message", {}).get("content") or "").strip()
        res = json.loads(content)
        return bool(res.get("verified"))
    except Exception as e:
        log.warning(f"Secondary check failed: {e}")
        # Fail closed for verification layer.
        return False


def verify(user_query: str, call: dict) -> VerificationResult:
    """The SG_CUBE Verification Stack:
    1. Rule-based checks (Hallucination, Schema, Security)
    2. Confidence scoring
    3. Conditional verifier model
    """
    name = (call.get("name") or "").strip()
    args = call.get("args") or {}
    reasoning = (call.get("reasoning") or "").strip()
    confidence = call.get("confidence", 0.0)

    # ── 1. Rule-based Safety Checks ──────────────────────────────────
    
    # A. Hallucination Check
    resolved = _resolve_name(name, args)
    if not resolved:
        return VerificationResult(False, error=f"Tool {name!r} not found in registry.")

    tool_obj = REGISTRY[resolved]

    # B. Malformed Check (Schema)
    params = tool_obj.schema.get("parameters", {})
    required = params.get("required", [])
    properties = params.get("properties", {})

    for req in required:
        if req not in args:
            return VerificationResult(False, error=f"Missing required argument {req!r} for tool {resolved!r}.")

    # Simple type validation
    for key, val in args.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type == "integer" and not isinstance(val, int):
                return VerificationResult(False, error=f"Argument {key!r} must be an integer.")
            if expected_type == "number" and not isinstance(val, (int, float)):
                return VerificationResult(False, error=f"Argument {key!r} must be a number.")
            if expected_type == "string" and not isinstance(val, str):
                return VerificationResult(False, error=f"Argument {key!r} must be a string.")
            if expected_type == "boolean" and not isinstance(val, bool):
                return VerificationResult(False, error=f"Argument {key!r} must be a boolean.")

    # C. Security Check (DANGEROUS / CONFIRM)
    from backend.core.tools.sandbox import guard
    # We don't call guard.check here because it would trigger a confirmation
    # event/token too early. We just check if it's DANGEROUS which is a hard block.
    if tool_obj.security == SecurityLevel.DANGEROUS:
         return VerificationResult(False, error=f"Tool {resolved!r} is marked DANGEROUS and is blocked.")

    # ── 2. Confidence Scoring ────────────────────────────────────────
    
    # If the Agent itself is not confident, we don't even bother the verifier model.
    try:
        conf_score = float(confidence)
    except (TypeError, ValueError):
        conf_score = 0.0
        
    if conf_score < 0.7:
        return VerificationResult(False, error=f"Agent confidence too low ({conf_score}) for tool {resolved!r}.")

    # ── 3. Conditional Verifier Model ────────────────────────────────
    
    # For critical tools, or if confidence is not perfect, we run the secondary model.
    needs_model = (tool_obj.security != SecurityLevel.TRUSTED) or (conf_score < 0.9)
    
    if needs_model:
        if not _secondary_check(user_query, resolved, args, reasoning):
            return VerificationResult(False, error="Action rejected by secondary model: logic or relevance mismatch.")

    return VerificationResult(True, reasoning=reasoning)
