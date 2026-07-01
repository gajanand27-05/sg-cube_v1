import logging
from enum import Enum
from typing import Any, Optional

from backend.core.events import get_bus

log = logging.getLogger(__name__)


class RecoveryPath(str, Enum):
    RETRY = "retry"        # Try the same tool again (transient errors)
    PIVOT = "pivot"        # Try a different tool or strategy
    FIX = "fix"            # Correct arguments and try again
    ESCALATE = "escalate"  # Ask the user for help
    ABORT = "abort"        # Stop immediately (security/fatal)


class SelfHealingEvent:
    def __init__(self, request_id: str, tool_name: str, error: str, path: RecoveryPath):
        self.request_id = request_id
        self.tool_name = tool_name
        self.error = error
        self.path = path

    def __repr__(self):
        return f"<SelfHealing: {self.tool_name} -> {self.path}>"


class SelfHealer:
    """Analyzes tool failures and recommends recovery strategies."""

    def analyze(self, tool_name: str, error: str, attempt: int = 1) -> RecoveryPath:
        err = error.lower()

        # ── 1. Security/Fatal (ABORT) ────────────────────────────────
        if "dangerous" in err or "blocked" in err or "permission denied" in err:
            return RecoveryPath.ABORT

        # ── 2. Transient (RETRY) ─────────────────────────────────────
        # If it's a timeout or connection issue, try again up to 3 times
        transient_signals = ["timeout", "connection", "503", "504", "temporary", "busy"]
        if any(sig in err for sig in transient_signals) and attempt < 3:
            return RecoveryPath.RETRY

        # ── 3. Malformed/Schema (FIX) ────────────────────────────────
        if "missing argument" in err or "type mismatch" in err or "hallucinated" in err:
            return RecoveryPath.FIX

        # ── 4. Tool-Specific Failure (PIVOT) ─────────────────────────
        # e.g. "app not found" -> pivot to "search_web"
        if "not found" in err or "no matches" in err:
            return RecoveryPath.PIVOT

        # ── 5. Unknown/Repeat Failure (ESCALATE) ─────────────────────
        return RecoveryPath.ESCALATE

    def get_instruction(self, path: RecoveryPath, tool_name: str, error: str) -> str:
        """Returns a string instruction for the Agent loop."""
        if path == RecoveryPath.RETRY:
            return f"The tool {tool_name} failed due to a transient error ({error}). I'm retrying automatically."
        if path == RecoveryPath.FIX:
            return f"The tool {tool_name} was malformed: {error}. Please correct the parameters and try again."
        if path == RecoveryPath.PIVOT:
            return f"The tool {tool_name} couldn't find the result ({error}). Try a different tool or search strategy."
        if path == RecoveryPath.ABORT:
            return f"The action was aborted for security: {error}. Apologize to the user and explain why."
        return f"The tool {tool_name} failed: {error}. Ask the user for clarification."


# Global instance
healer = SelfHealer()
