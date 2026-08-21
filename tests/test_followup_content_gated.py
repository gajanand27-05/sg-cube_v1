"""The follow-up window should close on absence of speech, not on a stopwatch.

The window was a flat 3s deadline from the moment the assistant stopped
speaking. Three seconds is shorter than a person takes to hear a sentence,
decide, and start talking — so a conversation needed the wake word again on
almost every turn, which is what makes it feel like a command line rather than
a conversation.

Content-gating it has a hazard that has to be designed for, not discovered:
T-wake-word-executes-ambient-audio means a window that stays open on any noise
lets a television drive the assistant. So the rules are:

  * absence closes it   — _FOLLOWUP_IDLE_S of nothing usable ends the chain
  * a failed attempt refreshes it — you mumbled, you get another full think,
    not the 400ms left on the old clock
  * two failed attempts close it — the ambient-audio brake, unchanged
  * a hard ceiling always wins — no chain of refreshes can outlive
    _FOLLOWUP_MAX_S without a fresh wake word

The ceiling is the part that makes this safe to ship: it bounds the blast
radius of the restricted-grammar gate, which can tell that speech happened but
not that it was addressed to us.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.daemon import wake_word as ww


class _Clock:
    """Monotonic time we control, so these assertions never sleep."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def listener(monkeypatch):
    """A listener with __init__ bypassed — it loads a Vosk model otherwise."""
    clock = _Clock()
    monkeypatch.setattr(ww.time, "monotonic", clock)
    obj = object.__new__(ww.WakeWordListener)
    obj._followup_until = 0.0
    obj._followup_hard_until = 0.0
    obj._empty_in_a_row = 0
    obj.wake_phrase = "onyx"
    obj._clock = clock
    return obj


def test_window_survives_a_realistic_thinking_pause(listener):
    """3s was shorter than hearing a sentence and deciding. The regression this
    exists for: the user answers a question and nothing is listening."""
    listener._open_followup()
    listener._clock.advance(4.0)          # longer than the old 3s deadline
    assert listener._followup_open(), "window shut during a normal pause"


def test_silence_eventually_closes_the_window(listener):
    """Absence is the close condition — it must actually close."""
    listener._open_followup()
    listener._clock.advance(ww._FOLLOWUP_IDLE_S + 0.1)
    assert not listener._followup_open()


def test_a_failed_attempt_grants_a_fresh_think(listener):
    """You spoke, nothing usable came back. You get another full idle period,
    not whatever milliseconds remained on the previous one."""
    listener._open_followup()
    listener._clock.advance(ww._FOLLOWUP_IDLE_S - 0.5)   # nearly expired
    listener._note_empty_capture()
    listener._clock.advance(ww._FOLLOWUP_IDLE_S - 0.5)   # would have died twice over
    assert listener._followup_open(), "a failed attempt did not refresh the window"


def test_two_failed_attempts_close_it(listener):
    """The ambient-audio brake. Unchanged behaviour, pinned here because the
    refresh above could otherwise make the window immortal."""
    listener._open_followup()
    listener._note_empty_capture()
    assert listener._followup_open(), "closed after a single failed attempt"
    listener._note_empty_capture()
    assert not listener._followup_open(), "two empty captures must end the chain"


def test_a_successful_command_clears_the_failure_count(listener):
    listener._open_followup()
    listener._note_empty_capture()
    listener._open_followup()             # a command landed
    listener._note_empty_capture()
    assert listener._followup_open(), "the empty counter did not reset on success"


def test_the_hard_ceiling_beats_any_chain_of_refreshes(listener):
    """A television talking at the mic must not hold the window open forever.
    Without this, content-gating is a strictly worse security posture than the
    stopwatch it replaced."""
    listener._open_followup()
    for _ in range(200):                  # far past the ceiling
        listener._clock.advance(1.0)
        listener._open_followup()         # pretend every second produced a command
    assert not listener._followup_open(), (
        "refreshes outlived the hard ceiling; ambient audio could drive the "
        "assistant indefinitely without a wake word")


def test_only_a_wake_word_revives_an_expired_chain(listener):
    """Reaching the ceiling must not permanently disable follow-up — but it
    must take a WAKE WORD to lift it, not another refresh. If a plain refresh
    revived it, the ceiling would be a speed bump rather than a brake."""
    listener._open_followup(new_chain=True)
    listener._clock.advance(ww._FOLLOWUP_MAX_S + 1)
    assert not listener._followup_open()

    listener._open_followup()             # a refresh must NOT resurrect it
    assert not listener._followup_open(), "a refresh lifted the ceiling"

    listener._open_followup(new_chain=True)   # the wake word does
    assert listener._followup_open(), "follow-up never recovered after a wake word"


def test_a_followup_turn_does_not_reset_the_ceiling(listener, monkeypatch):
    """The wiring, not just the helper.

    _start_turn carries new_chain through to _open_followup. If a turn
    triggered from inside the window reset the ceiling, every reply would
    renew the brake and a chain could run forever — the helper would still
    pass its own tests, because the defect lives in the caller.
    """
    from unittest.mock import patch

    listener.on_wake = lambda audio: True
    listener._turn_thread = None

    listener._open_followup(new_chain=True)
    ceiling_at_start = listener._followup_hard_until

    with patch.object(ww, "dogfooding_ledger"):
        listener._clock.advance(5.0)
        listener._start_turn(b"", new_chain=False)   # triggered from the window
        listener._turn_thread.join(5)

    assert listener._followup_hard_until == ceiling_at_start, (
        "a follow-up turn pushed the ceiling out; the chain would never end")
    assert listener._followup_open(), "the window should still be open mid-chain"


def test_a_wake_word_turn_does_reset_the_ceiling(listener):
    """The other half: a fresh wake word must grant a fresh chain, or a long
    conversation would leave the user unable to start a new one."""
    from unittest.mock import patch

    listener.on_wake = lambda audio: True
    listener._turn_thread = None

    listener._open_followup(new_chain=True)
    ceiling_at_start = listener._followup_hard_until

    with patch.object(ww, "dogfooding_ledger"):
        listener._clock.advance(5.0)
        listener._start_turn(b"", new_chain=True)
        listener._turn_thread.join(5)

    assert listener._followup_hard_until > ceiling_at_start, (
        "a wake word did not start a fresh chain")


def test_confirmation_window_can_exceed_the_idle_default(listener):
    """'Should I proceed?' needs longer than a normal pause — the user has to
    hear a question, weigh it, and answer."""
    listener._open_followup(window=20.0)
    listener._clock.advance(ww._FOLLOWUP_IDLE_S + 1)
    assert listener._followup_open(), "the confirmation window was truncated"
