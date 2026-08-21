"""If the assistant asks a question, it has to wait for the answer.

Reported live:

    [command] 'Close notepad.'
    [ai] response: I need your permission to close app. Should I proceed?
    [wake] follow-up window open for 3s
    ...nothing...
                                    "not even reading my proceed command"

There was no transcript of "proceed" at all — not a mis-hear, not a rejected
one. Nothing was listening.

The confirmation machinery itself was fine; verified separately that a pending
call resumes correctly even across the fresh ConversationContext that Brain
builds per turn. The failure was upstream: the follow-up window is 3s and it
starts when the assistant STOPS SPEAKING. After a ~3s question the user hears
it, thinks, and answers — by which time the mic has stopped listening.

Asking a question and then not waiting for the answer is its own bug,
independent of how good the transcription is.
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.pending_confirmation import Pending, store
from backend.daemon import wake_word as ww
from backend.server.config import settings


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear_all()
    yield
    store.clear_all()


def _listener(on_wake):
    listener = object.__new__(ww.WakeWordListener)
    listener.on_wake = on_wake
    listener.wake_phrase = "onyx"
    listener._turn_thread = None
    listener._followup_until = 0.0
    listener._followup_hard_until = 0.0
    listener._empty_in_a_row = 0
    return listener


def _pending():
    return Pending(calls=[{"name": "close_app", "args": {"name": "notepad"}}],
                   user_query="close notepad", tool_name="close app")


def _run_turn(listener):
    with patch.object(ww, "dogfooding_ledger"):
        listener._start_turn(b"")
        listener._turn_thread.join(5)


def test_a_pending_question_keeps_the_mic_open_longer():
    """The reported case."""
    listener = _listener(lambda audio: True)
    store.remember("s", _pending())

    t0 = time.monotonic()
    _run_turn(listener)
    remaining = listener._followup_until - t0

    assert remaining > ww._FOLLOWUP_IDLE_S + 1, (
        f"window was {remaining:.1f}s after the assistant asked a question; "
        "the user cannot hear it, think and answer inside "
        f"{ww._FOLLOWUP_IDLE_S:.0f}s"
    )
    assert remaining == pytest.approx(settings.confirmation_followup_window_s, abs=1.0)


def test_an_ordinary_turn_keeps_the_short_window():
    """The long window is for questions only. Leaving the mic open for 20s
    after every turn is how ambient speech gets executed — the whole point of
    T-wake-word-executes-ambient-audio.

    The ordinary window is now the content-gated idle budget rather than a
    flat 3s, and _FOLLOWUP_MAX_S bounds any chain of them; neither changes
    the rule this pins, which is that an ordinary turn must not inherit the
    confirmation window."""
    listener = _listener(lambda audio: True)

    t0 = time.monotonic()
    _run_turn(listener)
    remaining = listener._followup_until - t0

    assert remaining == pytest.approx(ww._FOLLOWUP_IDLE_S, abs=1.0), (
        f"ordinary turn left the mic open for {remaining:.1f}s"
    )


def test_an_expired_pending_does_not_hold_the_window_open():
    """A pending that can no longer be answered must not keep the mic open —
    that would be a long listening window with nothing to answer."""
    listener = _listener(lambda audio: True)
    p = _pending()
    p.created_at = time.monotonic() - (settings.confirmation_ttl_s + 5)
    store.remember("s", p)

    t0 = time.monotonic()
    _run_turn(listener)
    assert (listener._followup_until - t0) == pytest.approx(ww._FOLLOWUP_IDLE_S, abs=1.0)


def test_the_window_cannot_outlive_the_pending_it_waits_for():
    """Listening for an answer after the action has expired would collect a
    'yes' that then does nothing — worse than not listening."""
    assert settings.confirmation_followup_window_s < settings.confirmation_ttl_s


def test_awaiting_answer_does_not_consume_the_pending():
    """take() pops by design. The listener's check must NOT, or asking the
    question would itself discard the thing being asked about."""
    store.remember("s", _pending())
    assert store.awaiting_answer() is True
    assert store.awaiting_answer() is True
    assert store.take("s") is not None, "the check consumed the pending"


def test_a_failed_turn_does_not_open_any_window():
    """command_handled=False keeps the existing empty-capture behaviour."""
    listener = _listener(lambda audio: False)
    store.remember("s", _pending())
    _run_turn(listener)
    assert listener._empty_in_a_row == 1


if __name__ == "__main__":
    print("run via pytest")
