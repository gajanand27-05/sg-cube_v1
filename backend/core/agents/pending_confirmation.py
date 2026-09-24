"""The other half of the confirmation gate.

`commander.py` asked "I need your permission to X. Should I proceed?" and then
returned, discarding the call it was asking about. Nothing stored it and
nothing consumed a reply, so "yes" arrived as an unrelated new turn and the
action never ran. Every SYSTEM_WRITE tool not on the trusted allowlist, and
every DESTRUCTIVE tool, was unreachable by voice: it asked, you answered,
nothing happened.

This is the missing store. It is deliberately small and deliberately eager to
forget, because a remembered action that fires later on an ambiguous "yeah" is
a worse bug than the one being fixed:

  * one slot per session — a second prompt overwrites the first, so there is
    never a queue of half-authorised actions;
  * a short TTL (`settings.confirmation_ttl_s`);
  * `take()` POPS. The pending is consumed by the very next turn whatever that
    turn says, so an unanswered prompt cannot be answered three turns later by
    a "sure" aimed at something else entirely.

That last rule is why `take()` has no "peek" variant. Callers must take, then
decide.

The HUD answers the SAME slot (take_by_id). Each pending carries an
unguessable id and a digest of its exact tool calls; a HUD answer must present
both, so it can only approve what was shown, and only once — whichever of
voice or HUD answers first consumes it. Every pending is announced on the bus
(ConfirmationRequested) and its end is too (ConfirmationResolved), including a
timer-driven expiry, so the HUD never shows a question that can no longer be
answered. Expiry means refused: nothing runs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field

from backend.server.config import settings

log = logging.getLogger(__name__)

# The whole utterance must be one of these. Not a substring test: "yes but
# play something else" is a new instruction, not an authorisation, and
# treating it as one would execute the thing the user just talked past.
_AFFIRMATIVE = frozenset({
    "yes", "yeah", "yep", "yup", "ya", "yes please", "yes do it",
    "sure", "ok", "okay", "k", "alright", "all right", "affirmative",
    "proceed", "go ahead", "go for it", "do it", "please do", "do that",
    "confirm", "confirmed", "approve", "approved", "permission granted",
})

_NEGATIVE = frozenset({
    "no", "nope", "nah", "no thanks", "no thank you", "negative",
    "don't", "dont", "do not", "forget it", "leave it", "skip it",
    # "cancel" / "stop" / "never mind" / "abort" are absent on purpose: the
    # rule tier resolves those to the stop command and they never reach
    # Commander at all. They are handled by the TTL and by take()'s pop.
})

# Filler that carries no decision either way, stripped before matching so
# "ok please" and "yeah sure" still read as one affirmation.
_FILLER = frozenset({"please", "just", "then", "now", "sure", "ok", "okay"})


def classify_reply(text: str) -> str | None:
    """"yes" | "no" | None. None means the user said something else, which is
    a new request, not an answer."""
    if not text:
        return None
    cleaned = "".join(c for c in text.lower() if c.isalnum() or c.isspace() or c == "'")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    if cleaned in _AFFIRMATIVE:
        return "yes"
    if cleaned in _NEGATIVE:
        return "no"
    # Retry once with filler removed, so "yeah ok" and "ok then" still land.
    # Only helps when something non-filler remains to carry the meaning.
    words = [w for w in cleaned.split() if w not in _FILLER]
    stripped = " ".join(words)
    if stripped and stripped != cleaned:
        if stripped in _AFFIRMATIVE:
            return "yes"
        if stripped in _NEGATIVE:
            return "no"
    # An utterance made ENTIRELY of filler ("ok", "sure", "okay please") is an
    # affirmation — those words are in _AFFIRMATIVE already, but the all-filler
    # case strips to empty and would otherwise fall through to None.
    if not stripped and all(w in _FILLER for w in cleaned.split()):
        return "yes"
    return None


def calls_digest(calls: list[dict]) -> str:
    """Hash of exactly what would run: tool names and arguments, canonically."""
    canon = [{"name": c.get("name"), "args": c.get("args") or {}} for c in calls]
    blob = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class Pending:
    calls: list[dict]
    user_query: str
    tool_name: str
    is_critical: bool = False
    created_at: float = field(default_factory=time.monotonic)
    prompt: str = ""
    details: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: secrets.token_urlsafe(16))

    @property
    def digest(self) -> str:
        return calls_digest(self.calls)

    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > settings.confirmation_ttl_s


def _publish(event) -> None:
    # Telemetry must never be why a confirmation breaks.
    try:
        from backend.core.events import Priority, get_bus

        get_bus().publish(event, priority=Priority.NORMAL)
    except Exception as e:  # noqa: BLE001
        log.debug("could not publish %s: %s", type(event).__name__, e)


def resolved(pending: "Pending", outcome: str) -> None:
    from backend.daemon.ui_events import ConfirmationResolved

    _publish(ConfirmationResolved(id=pending.id, outcome=outcome))


class PendingStore:
    """One slot per session. Thread-safe: the voice path and the HTTP path
    reach Commander from different threads and event loops."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, Pending] = {}

    def remember(self, session_id: str, pending: Pending) -> None:
        from backend.daemon.ui_events import ConfirmationRequested

        with self._lock:
            replaced = self._slots.get(session_id)
            if replaced is not None:
                log.info("Confirmation for %r replaced an unanswered one",
                         pending.tool_name)
            self._slots[session_id] = pending
        if replaced is not None:
            resolved(replaced, "superseded")
        # Expiry is still enforced lazily by take()/take_by_id(); the timer
        # exists so the HUD hears about it and drops the dialog. +0.5s so it
        # never fires a hair before expired() agrees.
        t = threading.Timer(settings.confirmation_ttl_s + 0.5, self._expire,
                            args=(session_id, pending.id))
        t.daemon = True
        t.start()
        _publish(ConfirmationRequested(
            id=pending.id, digest=pending.digest, tool=pending.tool_name,
            prompt=pending.prompt, details=list(pending.details),
            critical=pending.is_critical, expires_in_s=settings.confirmation_ttl_s))

    def _expire(self, session_id: str, pending_id: str) -> None:
        with self._lock:
            p = self._slots.get(session_id)
            if p is None or p.id != pending_id:
                return  # already answered, or replaced
            self._slots.pop(session_id, None)
        log.info("Confirmation for %r expired unanswered — refused", p.tool_name)
        resolved(p, "expired")

    def take(self, session_id: str) -> Pending | None:
        """Pop the slot. Returns None if empty or expired — either way the
        slot is now clear. The caller publishes the outcome (resolved())."""
        with self._lock:
            pending = self._slots.pop(session_id, None)
        if pending is None:
            return None
        if pending.expired():
            log.info("Confirmation for %r expired after %.0fs",
                     pending.tool_name, settings.confirmation_ttl_s)
            resolved(pending, "expired")
            return None
        return pending

    def take_by_id(self, pending_id: str, digest: str) -> tuple[Pending | None, str]:
        """The HUD's answer path. -> (pending, "") or (None, why not).

        Pops only on an exact id AND digest match, so a stale or forged answer
        cannot consume — or approve — a different action. Single use: a second
        answer finds nothing."""
        with self._lock:
            for sid, p in self._slots.items():
                if secrets.compare_digest(p.id, pending_id or ""):
                    if not secrets.compare_digest(p.digest, digest or ""):
                        return None, "that answer does not match the pending action"
                    self._slots.pop(sid)
                    break
            else:
                return None, "nothing is waiting for that answer (already answered or expired)"
        if p.expired():
            resolved(p, "expired")
            return None, "the question expired"
        return p, ""

    def awaiting_answer(self) -> bool:
        """Is any session waiting on a "should I proceed?".

        Non-popping on purpose, and the only read that is. `take()` pops
        because a stale pending must not be answerable three turns later —
        but the wake listener needs to know a question is on the table WITHOUT
        consuming it, so it can keep listening for the answer.
        """
        with self._lock:
            return any(not p.expired() for p in self._slots.values())

    def clear(self, session_id: str) -> None:
        with self._lock:
            p = self._slots.pop(session_id, None)
        if p is not None:
            resolved(p, "cancelled")

    def clear_all(self) -> None:
        """"stop" means stop — including any action awaiting authorisation."""
        with self._lock:
            gone = list(self._slots.values())
            self._slots.clear()
        for p in gone:
            resolved(p, "cancelled")


store = PendingStore()
