import json
import logging
import re
from typing import Any

import httpx

from backend.core.tools.registry import REGISTRY, SecurityLevel, _resolve_name
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
    def __init__(self, is_valid: bool, error: str = "", reasoning: str = ""):
        self.is_valid = is_valid
        self.error = error
        self.reasoning = reasoning


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


def verify(user_query: str, call: dict, is_multi_step: bool = False) -> VerificationResult:
    """The SG_CUBE Verification Stack:
    1. Rule-based checks (Hallucination, Schema, Security, Injection)
    2. Confidence scoring (Routing Signal)
    3. Conditional verifier model (Only when needed)
    """
    name = (call.get("name") or "").strip()
    args = call.get("args") or {}
    reasoning = (call.get("reasoning") or "").strip()
    
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

    # C. Injection & Blacklist Check
    malicious_reason = _is_malicious(args)
    if malicious_reason:
        return VerificationResult(False, error=malicious_reason)

    # D. Security Check (DANGEROUS / CONFIRM)
    if tool_obj.security == SecurityLevel.DANGEROUS:
         return VerificationResult(False, error=f"Tool {resolved!r} is marked DANGEROUS and is blocked.")

    # ── 2. Confidence Scoring (Routing Signal) ───────────────────────
    
    try:
        conf_score = float(call.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf_score = 0.0

    # ── 3. Conditional Verifier Model ────────────────────────────────
    # We only trigger the heavy secondary model if:
    # - Confidence is low (< 0.80)
    # - The tool requires confirmation (CONFIRM_REQUIRED)
    # - It's part of a multi-step plan
    
    needs_deep_verification = (
        conf_score < 0.80 or 
        tool_obj.security == SecurityLevel.CONFIRM_REQUIRED or
        is_multi_step
    )
    
    if needs_deep_verification:
        log.info(f"Triggering deep verification for {resolved!r} (conf={conf_score}, multi={is_multi_step})")
        if not _secondary_check(user_query, resolved, args, reasoning):
            return VerificationResult(
                False, 
                error="Action rejected by secondary verifier: logic or relevance mismatch."
            )

    return VerificationResult(True, reasoning=reasoning)
