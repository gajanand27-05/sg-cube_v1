"""An expired chain must not announce that it is listening.

From the live WhatsApp turn:

    [ai] response: What would you like the message to say? (latency: 6557ms)
    [wake] listening — 8s idle, -1s left in this chain
    [wake] heard wake: '[unk] [unk] [unk] onyx' (rms=1301)
    [command] 'Hi, how are you doing?'

Onyx asked a question and then printed "listening" while the window was
already shut. The user answered into a dead microphone; the answer only landed
because Vosk hallucinated the wake word, which started a fresh chain that knew
nothing about the pending question.

Mechanism, and it is entirely in `_open_followup`:

    if new_chain or self._followup_hard_until <= 0.0:
        self._followup_hard_until = now + _FOLLOWUP_MAX_S
    self._followup_until = min(now + window, self._followup_hard_until)

A follow-up turn passes `new_chain=False`, and an EXPIRED ceiling is still a
positive timestamp, so the reset is skipped and `_followup_until` is clamped to
a moment in the past. The window opens already closed. The line printed on the
next line of `_start_turn` never asked `_followup_open()` — it assumed.

The 45s ceiling is correct and is NOT touched here: it is the brake against
ambient audio driving the assistant. What is wrong is only the claim. A closed
window should say so.

Note on coverage: the case that actually bit was a planner CLARIFICATION
("what would you like the message to say?"), and nothing in the tree records
that a turn ended by asking one — `_pending_store.awaiting_answer()` covers
yes/no confirmations only. So the confirmation path is the closest reachable
proxy and is tested below; the clarification case cannot be pinned until a
structured slot exists for it.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.daemon import wake_word as ww


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def listener(monkeypatch):
    """__init__ bypassed — it loads a Vosk model otherwise."""
    clock = _Clock()
    monkeypatch.setattr(ww.time, "monotonic", clock)
    obj = object.__new__(ww.WakeWordListener)
    obj._followup_until = 0.0
    obj._followup_hard_until = 0.0
    obj._empty_in_a_row = 0
    obj.wake_phrase = "onyx"
    obj._clock = clock
    return obj


def _exhaust_the_chain(listener):
    """Put the listener exactly where the WhatsApp turn was: a chain whose
    ceiling has passed, reached through ordinary follow-up turns."""
    listener._open_followup(new_chain=True)          # the wake word
    listener._clock.advance(ww._FOLLOWUP_MAX_S + 1)  # 45s of conversation
    listener._open_followup(ww._FOLLOWUP_IDLE_S, new_chain=False)
    assert not listener._followup_open(), "fixture precondition: chain is dead"


def test_an_expired_chain_does_not_say_listening(listener):
    """The regression. The window is shut, so the notice must not claim
    otherwise."""
    _exhaust_the_chain(listener)
    notice = listener._followup_notice(ww._FOLLOWUP_IDLE_S)

    assert "listening" not in notice.lower(), (
        f"expired chain announced {notice!r} — the microphone is closed and "
        "the user is being told it is open"
    )


def test_the_expired_notice_says_how_to_continue(listener):
    """Telling the user it stopped is only useful with the way back."""
    _exhaust_the_chain(listener)
    notice = listener._followup_notice(ww._FOLLOWUP_IDLE_S)
    assert "onyx" in notice.lower(), (
        f"{notice!r} does not tell the user the wake word will restart it"
    )


def test_a_live_chain_still_reports_listening(listener):
    """Guard against fixing this by silencing the notice everywhere."""
    listener._open_followup(new_chain=True)
    notice = listener._followup_notice(ww._FOLLOWUP_IDLE_S)
    assert "listening" in notice.lower(), notice
    assert "8s idle" in notice, notice


def test_the_notice_never_reports_negative_time_left(listener):
    """'-1s left in this chain' is the shape the bug took in the log."""
    _exhaust_the_chain(listener)
    notice = listener._followup_notice(ww._FOLLOWUP_IDLE_S)
    assert "-" not in notice, f"negative remaining time leaked into {notice!r}"


def test_a_pending_confirmation_on_a_dead_chain_is_still_dead(listener):
    """The case closest to what bit the user.

    `_start_turn` widens the window to `confirmation_followup_window_s` when a
    confirmation is outstanding — but `_open_followup` clamps that to the
    ceiling, so on an exhausted chain the longer window buys NOTHING. Onyx asks
    "should I proceed?" and is deaf for the answer.

    This test does not change that behaviour (the ceiling stays), it pins that
    we at least stop claiming to listen.
    """
    from backend.server.config import settings

    _exhaust_the_chain(listener)
    listener._open_followup(settings.confirmation_followup_window_s,
                            new_chain=False)

    assert not listener._followup_open(), (
        "a confirmation window outlived the chain ceiling — that would be a "
        "change to the ambient-audio brake, which is out of scope here"
    )
    notice = listener._followup_notice(settings.confirmation_followup_window_s)
    assert "listening" not in notice.lower(), (
        f"asked a question, window is shut, and still announced {notice!r}"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs the pytest fixture)")
