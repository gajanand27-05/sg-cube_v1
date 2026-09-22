"""A question Onyx asked, held across the chain that asked it.

Distinct from `pending_confirmation.PendingStore`, deliberately. That slot
answers "should I proceed?" with yes/no and its forget-early behaviour is a
safety property: an unanswered permission prompt must not be authorisable by a
"sure" meant for something else three turns later. This one holds a half-built
TOOL CALL waiting on a missing argument, and has a different shape, a different
lifetime and a different consumer (the planner, not a yes/no classifier).

The failure it closes, from a live log:

    [command] 'to send a whatsapp message to sharat'
    Guardian rejected: ["Missing required argument 'message' for tool 'send_whatsapp'."]
    [ai] response: What would you like the message to say?
    [wake] listening — 8s idle, -1s left in this chain      <- already dead
    [wake] heard wake: '[unk] [unk] [unk] onyx' (rms=1301)
    [command] 'Hi, how are you doing?'
    [ai] response: I'm doing great, thank you for asking!

The answer arrived on a NEW chain, which knew nothing about the question, so
it was read as a greeting and the message was never sent.

Two design rules, both load-bearing:

1. The 45s follow-up ceiling is NOT extended to fix this. That ceiling is the
   brake on ambient audio driving the assistant — under a restricted grammar we
   can tell speech happened but not that it was addressed to us. Instead the
   QUESTION outlives the chain, and the wake word is the authorisation to
   answer it. A dead window plus a fresh "Onyx" is a deliberate act by the user.

2. The slot is never filled here. `context_for()` hands the planner the pending
   question as context and the planner decides whether the new utterance
   answers it; whatever it decides, the slot is consumed. If this module could
   write the utterance into `args`, then "Onyx, what's the weather" with a
   WhatsApp pending would send the weather to Sharath. There is deliberately no
   fill()/answer() method, and a test pins their absence.

Nothing here bypasses anything: a completed call is emitted by the planner and
runs the normal Guardian + confirmation path.
"""
import logging
import re
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# How long a half-built action stays answerable.
#
# UNDER REVIEW — flagged for the user, not measured. The budget it has to
# cover: a follow-up window that has already expired, hearing the question,
# deciding, saying the wake word, a capture that can run to the 10s cap, and
# STT. 60s covers that with room for a pause.
#
# Shorter than confirmation_ttl_s (90s) on purpose: a half-built message to a
# real person is a riskier thing to leave lying around than a yes/no prompt,
# because the thing that completes it is arbitrary dictated text rather than
# one word from a closed set.
CLARIFICATION_TTL_S = 60

# Built to match verifier.py's wording exactly. healing.py already couples to
# this string; a reword there breaks the feature, so a test asserts the phrase
# still comes out of the verifier.
_MISSING_ARG_RE = re.compile(
    r"missing required argument '([^']+)' for tool '([^']+)'", re.IGNORECASE)


def parse_missing_arg(error: str) -> tuple[str, str] | None:
    """(param, tool) from a Guardian missing-argument error, or None."""
    match = _MISSING_ARG_RE.search(error or "")
    return (match.group(1), match.group(2)) if match else None


@dataclass
class Clarification:
    tool: str
    args: dict               # what the planner DID supply — never re-asked
    missing: str             # the parameter the Guardian rejected it for
    question: str            # what Onyx actually said out loud
    created_at: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > CLARIFICATION_TTL_S


def context_for(clar: Clarification) -> str:
    """The pending question, phrased for the planner.

    Explicitly licenses ignoring it. Without that the planner forces whatever
    it is given into the pending slot — which is the same bug as auto-filling,
    just relocated into the prompt.
    """
    return (
        f"[pending question] You asked: {clar.question!r}\n"
        f"You asked it because the tool {clar.tool!r} was missing its "
        f"{clar.missing!r} argument. Arguments already known: {clar.args!r}.\n"
        f"If the user's next message answers that question, emit the completed "
        f"{clar.tool!r} call using the known arguments plus the answer, and do "
        f"not ask again for anything already listed.\n"
        f"If the next message is an UNRELATED request, ignore this pending "
        f"question entirely and handle the new request instead. Do not force "
        f"an unrelated utterance into the {clar.missing!r} argument."
    )


class ClarificationStore:
    """One slot per session. Thread-safe for the same reason PendingStore is:
    the voice path and the HTTP path reach Commander from different threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict = {}

    def remember(self, session_id, clar: Clarification) -> None:
        with self._lock:
            if session_id in self._slots:
                log.info("Clarification for %r replaced an unanswered one",
                         clar.tool)
            self._slots[session_id] = clar

    def take(self, session_id) -> Clarification | None:
        """Pop the slot. None if empty or expired — either way it is now clear.

        Popping unconditionally is what "consumed either way" means: an
        ignored question must not stay answerable on a later turn.
        """
        with self._lock:
            clar = self._slots.pop(session_id, None)
        if clar is None:
            return None
        if clar.expired():
            log.info("Clarification for %r expired after %ds",
                     clar.tool, CLARIFICATION_TTL_S)
            return None
        return clar

    def awaiting_answer(self) -> bool:
        """Is a question outstanding? Non-popping — the wake listener asks this
        to decide whether to keep listening, and must not consume it."""
        with self._lock:
            return any(not c.expired() for c in self._slots.values())

    def clear_all(self) -> None:
        """"stop"/"never mind" means the half-built action is abandoned."""
        with self._lock:
            self._slots.clear()


store = ClarificationStore()
