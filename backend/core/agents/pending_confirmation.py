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
"""
from __future__ import annotations

import logging
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


@dataclass
class Pending:
    calls: list[dict]
    user_query: str
    tool_name: str
    is_critical: bool = False
    created_at: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > settings.confirmation_ttl_s


class PendingStore:
    """One slot per session. Thread-safe: the voice path and the HTTP path
    reach Commander from different threads and event loops."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, Pending] = {}

    def remember(self, session_id: str, pending: Pending) -> None:
        with self._lock:
            if session_id in self._slots:
                log.info("Confirmation for %r replaced an unanswered one",
                         pending.tool_name)
            self._slots[session_id] = pending

    def take(self, session_id: str) -> Pending | None:
        """Pop the slot. Returns None if empty or expired — either way the
        slot is now clear."""
        with self._lock:
            pending = self._slots.pop(session_id, None)
        if pending is None:
            return None
        if pending.expired():
            log.info("Confirmation for %r expired after %.0fs",
                     pending.tool_name, settings.confirmation_ttl_s)
            return None
        return pending

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._slots.pop(session_id, None)

    def clear_all(self) -> None:
        """"stop" means stop — including any action awaiting authorisation."""
        with self._lock:
            self._slots.clear()


store = PendingStore()
