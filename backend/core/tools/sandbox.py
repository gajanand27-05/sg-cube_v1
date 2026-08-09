import secrets
import time
from typing import Any

from backend.core.events import get_bus
from backend.core.tools.registry import REGISTRY, SecurityLevel, ToolResult

# A pending confirmation is an armed action. Leaving it armed indefinitely
# means a "yes" an hour later still fires something the user has forgotten
# asking about — and _pending was also unbounded.
PENDING_TTL_S = 120.0


class PermissionDenied(Exception):
    pass


class PendingConfirmation:
    def __init__(self, token: str, tool_name: str, args: dict, spoken_code: str | None = None):
        self.token = token
        self.tool_name = tool_name
        self.args = args
        # What the user is asked to say. The UI keeps using `token`.
        self.spoken_code = spoken_code


class PermissionGuard:
    """Intercepts tool calls to enforce security levels."""

    def __init__(self):
        # token -> (tool name, args, expiry, spoken code)
        self._pending: dict[str, tuple[str, dict, float, str]] = {}
        self._codes: dict[str, str] = {}   # spoken code -> token

    def _purge_expired(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        dead = [t for t, (_n, _a, exp, _c) in self._pending.items() if exp <= now]
        for t in dead:
            _n, _a, _e, code = self._pending.pop(t)
            self._codes.pop(code, None)

    def _new_spoken_code(self) -> str:
        """A 4-digit code the user can actually say.

        The urlsafe token is 22 characters of base64 — correct as a machine
        credential, and unspeakable, so the voice path it was quoted in
        ("please say 'confirm <token>'") became impossible to complete. The
        token is unchanged and still what the UI sends; this is a second,
        short handle for speech only.

        4 digits is deliberate. It is not the security boundary — the boundary
        is that a code is single-use, expires in PENDING_TTL_S, and only ever
        arms one specific already-requested action. Guessing it blind would
        need thousands of spoken attempts inside two minutes.
        """
        for _ in range(50):
            code = f"{secrets.randbelow(10000):04d}"
            if code not in self._codes:
                return code
        raise RuntimeError("could not allocate a free confirmation code")

    def check(self, name: str, args: dict) -> ToolResult | None:
        """Checks if a tool can be executed. 
        Returns None if OK, or a ToolResult (BLOCKED/PENDING) if not.
        """
        tool = REGISTRY.get(name)
        if not tool:
            return None

        if tool.security == SecurityLevel.CRITICAL:
            # Critical actions are blocked at this level unless the Guardian
            # or a specific confirmation flow handles them.
            return ToolResult.blocked(f"Tool {name!r} is marked CRITICAL and requires manual approval via the Guardian Agent.")

        if tool.security == SecurityLevel.CAUTION:
            # Not uuid4()[:8]: 8 hex chars is 32 bits, and this token is the
            # only thing standing between a caller and executing a CAUTION tool.
            self._purge_expired()
            token = secrets.token_urlsafe(16)
            code = self._new_spoken_code()
            self._pending[token] = (name, args, time.monotonic() + PENDING_TTL_S, code)
            self._codes[code] = token

            # Publish event so the UI can show a confirmation dialog
            get_bus().publish(PendingConfirmation(token, name, args, spoken_code=code))

            return ToolResult.pending(
                confirmation_token=token,
                message=(f"I need your confirmation to run {name}. "
                         f"Say 'confirm {code}' or click OK.")
            )

        return None

    async def confirm(self, token: str) -> ToolResult:
        """Execute a pending tool call, by token or by spoken code.

        Async because `Tool.__call__` is: the previous sync version returned
        the un-awaited coroutine, so a caller that checked the result would
        have got a coroutine object instead of a ToolResult and the confirmed
        tool would never have run. There are no callers yet, which is the only
        reason that never bit — wiring the confirmation UI to it would have.
        """
        self._purge_expired()
        key = (token or "").strip()
        # Voice path: accept the short code, and tolerate it being transcribed
        # with separators ("confirm 4-8-2-1" / "4 8 2 1").
        if key not in self._pending:
            digits = "".join(ch for ch in key if ch.isdigit())
            key = self._codes.get(key) or self._codes.get(digits) or key

        if key not in self._pending:
            return ToolResult.error(f"Invalid or expired confirmation token: {token}")

        name, args, _exp, code = self._pending.pop(key)
        self._codes.pop(code, None)   # single use
        tool = REGISTRY.get(name)
        if not tool:
            return ToolResult.error(f"Tool {name!r} no longer exists.")

        # Bypass check since we have explicit user confirmation now
        return await tool(**args)


# Global instance
guard = PermissionGuard()
