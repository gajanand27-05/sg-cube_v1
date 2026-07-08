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

        # ── 2. Window closed mid-op (RETRY once, then ABORT) ────────
        # Phase 1: windowing.py raises this when SetWindowPos hits the
        # target after the user closed it. One retry catches the "user
        # tapped X while I was mid-move" case; a second failure means
        # the target is genuinely gone.
        if "closed mid-operation" in err or "window closed" in err or "no longer exists" in err:
            return RecoveryPath.RETRY if attempt < 2 else RecoveryPath.ABORT

        # ── 3. Browser: navigation timeout (RETRY once, then ABORT) ──
        # Phase 2: fires BEFORE the generic transient-signals RETRY block
        # below, because "timeout" is a substring of "navigation timeout"
        # and would otherwise get up-to-3 retries. Nav timeout gets one.
        if "navigation timeout" in err:
            return RecoveryPath.RETRY if attempt < 2 else RecoveryPath.ABORT

        # ── 4. Transient (RETRY) ─────────────────────────────────────
        transient_signals = ["timeout", "connection", "503", "504", "temporary", "busy"]
        if any(sig in err for sig in transient_signals) and attempt < 3:
            return RecoveryPath.RETRY

        # ── 4. Malformed/Schema (FIX) ────────────────────────────────
        if "missing argument" in err or "type mismatch" in err or "hallucinated" in err:
            return RecoveryPath.FIX

        # ── 5. Elevated / access-denied window (ESCALATE with context) ─
        # Phase 1: SetWindowPos on an admin-elevated window fails with
        # ERROR_ACCESS_DENIED. Non-elevated SG_CUBE cannot recover this;
        # the user has to move it themselves or run us elevated.
        if "access denied" in err or "elevated" in err:
            return RecoveryPath.ESCALATE

        # ── 6. Browser: launch failed (ESCALATE) ─────────────────────
        # Phase 2: Playwright's chromium didn't start. Recovery requires
        # `playwright install chromium` or fixing the profile dir — user
        # action, not something the agent loop can retry.
        if "browser unavailable" in err or "chromium launch failed" in err:
            return RecoveryPath.ESCALATE

        # ── 7 (was): browser navigation timeout moved to section 3 to fire
        # before the generic transient "timeout" match.

        # ── 8. Browser: element resolution / not-found (PIVOT) ───────
        # Phase 2: click/type target didn't resolve — re-read page, retry
        # match with a more specific description.
        if "no element matching" in err or "no editable target" in err or "tab_id" in err and "not found" in err:
            return RecoveryPath.PIVOT

        # ── 9. Phase 3 canvas: schema validation failure (ABORT) ─────
        # If the model produced a widget layout the schema rejects, retrying
        # rarely helps — the model needs a hint from the surfaced error, not
        # another blind attempt.
        if "canvas schema invalid" in err or "canvas map widget rejected" in err:
            return RecoveryPath.ABORT

        # ── 10. Phase 3 data-source: provider rate-limited (PIVOT) ───
        # Do NOT retry-hammer. Serve cached (the tool already tried) or ask
        # the assistant to try an alternate data source.
        if "rate limit" in err or "rate-limited" in err or "too many requests" in err or "http 429" in err:
            return RecoveryPath.PIVOT

        # ── 11. Phase 3 data-source: not configured (ESCALATE) ───────
        # An optional keyed provider was chosen but the API key is missing.
        # Only the user can set it.
        if "not configured" in err or "api_key" in err or "api key" in err:
            return RecoveryPath.ESCALATE

        # ── 12. Tool-Specific Failure (PIVOT) ────────────────────────
        # e.g. "no window matching" -> re-list windows and retry match.
        if "not found" in err or "no matches" in err or "no window matching" in err:
            return RecoveryPath.PIVOT

        # ── 13. Unknown/Repeat Failure (ESCALATE) ────────────────────
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
