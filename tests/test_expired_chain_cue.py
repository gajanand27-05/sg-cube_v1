"""When the chain dies with a question outstanding, say so out loud.

Fix 1 stopped the log from claiming "listening — -1s left in this chain". But
the user does not watch the terminal, and the case that actually cost a
WhatsApp message was Onyx asking a question and then going deaf without any
perceivable sign of it.

Two signals, deliberately different in scope:

  * a UI event on EVERY expiry — cheap, silent, and the HUD is where a
    developer looks;
  * a spoken cue ONLY when a question is outstanding. Speaking on every
    expiry would add a sentence to the end of every single exchange, which
    trains the user to talk over Onyx — the opposite of the goal.

"Outstanding question" means either kind: a yes/no confirmation or a
PendingClarification. The clarification half is the case from the log, and it
could not be tested until the clarification slot existed.

No new sound assets. Deliberately NOT _play_chime(): that chime means "I am
listening", so using it to announce the opposite is worse than silence.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.agents import pending_clarification as pc
from backend.daemon import wake_word as ww


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def listener(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ww.time, "monotonic", clock)
    obj = object.__new__(ww.WakeWordListener)
    obj._followup_until = 0.0
    obj._followup_hard_until = 0.0
    obj._empty_in_a_row = 0
    obj.wake_phrase = "onyx"
    obj._clock = clock
    pc.store.clear_all()
    yield obj
    pc.store.clear_all()


@pytest.fixture
def spoken(monkeypatch):
    said = []
    monkeypatch.setattr(ww, "_speak_cue", lambda text: said.append(text))
    return said


@pytest.fixture
def published(monkeypatch):
    events = []

    class _Bus:
        def publish(self, event, priority=None):
            events.append(event)

    monkeypatch.setattr(ww, "get_bus", lambda: _Bus())
    return events


def _kill_the_chain(listener):
    listener._open_followup(new_chain=True)
    listener._clock.advance(ww._FOLLOWUP_MAX_S + 1)
    listener._open_followup(ww._FOLLOWUP_IDLE_S, new_chain=False)
    assert not listener._followup_open()


def _pend_a_clarification():
    pc.store.remember(None, pc.Clarification(
        tool="send_whatsapp", args={"contact": "Sharath"}, missing="message",
        question="What would you like the message to say?"))


def test_a_pending_clarification_gets_a_spoken_cue(listener, spoken, published):
    """The case from the log, finally testable."""
    _pend_a_clarification()
    _kill_the_chain(listener)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)

    assert spoken, (
        "Onyx asked for the message body, went deaf, and gave the user no "
        "perceivable sign of either"
    )
    assert "onyx" in spoken[0].lower(), (
        f"the cue {spoken[0]!r} does not tell the user how to answer"
    )


def test_an_expiry_with_no_question_is_silent(listener, spoken, published):
    """Scope. A cue on every expiry ends every exchange with an extra
    sentence, which trains the user to talk over Onyx."""
    _kill_the_chain(listener)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)
    assert spoken == [], f"spoke on a plain expiry: {spoken!r}"


def test_a_live_chain_is_silent_even_with_a_question_pending(listener, spoken):
    """Still listening — there is nothing to announce."""
    _pend_a_clarification()
    listener._open_followup(new_chain=True)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)
    assert spoken == [], f"spoke while still listening: {spoken!r}"


def test_a_pending_confirmation_also_gets_the_cue(listener, spoken, published):
    """The other kind of outstanding question."""
    from backend.core.agents.pending_confirmation import Pending, store as conf

    conf.clear_all()
    try:
        conf.remember(None, Pending(calls=[], user_query="q",
                                    tool_name="send_whatsapp"))
        _kill_the_chain(listener)
        listener._announce_followup(ww._FOLLOWUP_IDLE_S)
        assert spoken, "a dead chain with a confirmation outstanding was silent"
    finally:
        conf.clear_all()


def test_every_expiry_publishes_a_ui_event(listener, spoken, published):
    """The silent half, on every expiry including the unremarkable ones."""
    _kill_the_chain(listener)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)

    names = [type(e).__name__ for e in published]
    assert "FollowUpExpired" in names, names


def test_a_live_chain_publishes_no_expiry_event(listener, spoken, published):
    listener._open_followup(new_chain=True)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)
    assert [type(e).__name__ for e in published] == []


def test_the_cue_does_not_reuse_the_listening_chime():
    """_play_chime means "I am listening". Using it to announce the opposite
    is worse than saying nothing."""
    import ast
    import inspect
    import textwrap

    # Parsed, not grepped: the method's docstring explains WHY it avoids the
    # chime, so a substring check fails on its own justification. What matters
    # is that nothing CALLS it.
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(ww.WakeWordListener._announce_followup)))
    called = {
        (node.func.id if isinstance(node.func, ast.Name) else
         getattr(node.func, "attr", ""))
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert not any("chime" in name.lower() for name in called), (
        f"the expiry announcement calls {sorted(called)} — the chime means "
        "'I am listening', so using it to announce the opposite is worse "
        "than saying nothing"
    )


def test_start_turn_uses_the_announcer():
    """Wiring guard."""
    import inspect

    src = inspect.getsource(ww.WakeWordListener._start_turn)
    assert "_announce_followup" in src, (
        "the announcer exists but _start_turn still prints directly, so none "
        "of it reaches the user"
    )


def test_a_failing_cue_cannot_kill_the_listener(listener, published, monkeypatch):
    """This runs on the wake worker thread. An exception here would take the
    turn thread down and the failure would look like a dead assistant."""
    _pend_a_clarification()

    def _boom(_text):
        raise RuntimeError("no audio device")

    monkeypatch.setattr(ww, "_speak_cue", _boom)
    _kill_the_chain(listener)
    listener._announce_followup(ww._FOLLOWUP_IDLE_S)   # must not raise


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
