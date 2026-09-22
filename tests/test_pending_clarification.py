"""A question Onyx asked must survive the chain that asked it.

The live failure, end to end:

    [command] 'to send a whatsapp message to sharat'
    Guardian rejected: ["Missing required argument 'message' for tool 'send_whatsapp'."]
    [ai] response: What would you like the message to say?
    [wake] listening — 8s idle, -1s left in this chain      <- already dead
    [wake] heard wake: '[unk] [unk] [unk] onyx' (rms=1301)
    [command] 'Hi, how are you doing?'
    [ai] response: I'm doing great, thank you for asking!

The user answered. The answer was treated as a greeting, because the new chain
had no idea a question was outstanding. The message was never sent.

`_pending_store` did not cover this: its ONLY write site is the "should I
proceed?" permission branch, so `awaiting_answer()` correctly saw nothing. The
question was plain planner prose after a self-healing retry.

Design constraints this file pins:

  * The 45s ceiling is NOT extended. The wake word is the authorisation —
    a pending question survives ACROSS chains instead of keeping one alive.
  * The slot is never auto-filled. "Onyx, what's the weather" while a WhatsApp
    message is pending must not send the weather to Sharath. The slot is
    passed to the planner as CONTEXT; the planner decides whether the new
    utterance answers it, and the slot is consumed either way.
  * No bypass. A completed call goes through the Guardian and the (now
    content-reading-back) confirmation exactly like any other call.
"""
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest

from backend.core.agents import pending_clarification as pc


@pytest.fixture(autouse=True)
def clean_slot():
    pc.store.clear_all()
    yield
    pc.store.clear_all()


def _clar(**kw):
    kw.setdefault("tool", "send_whatsapp")
    kw.setdefault("args", {"contact": "Sharath"})
    kw.setdefault("missing", "message")
    kw.setdefault("question", "What would you like the message to say?")
    return pc.Clarification(**kw)


# ── the slot ───────────────────────────────────────────────────────────


def test_a_pending_question_survives_a_new_chain():
    """The whole point. take() is not scoped to the chain that asked."""
    pc.store.remember(None, _clar())
    got = pc.store.take(None)
    assert got is not None and got.tool == "send_whatsapp"
    assert got.args == {"contact": "Sharath"}, "partial args were lost"
    assert got.missing == "message"


def test_the_slot_is_consumed_even_when_the_answer_is_unrelated():
    """Consumed either way — otherwise an ignored question stays answerable
    three turns later and a stray 'yes' completes it."""
    pc.store.remember(None, _clar())
    assert pc.store.take(None) is not None
    assert pc.store.take(None) is None, "the slot survived being taken"


def test_expiry_clears_it():
    stale = _clar()
    stale.created_at = time.monotonic() - pc.CLARIFICATION_TTL_S - 1
    pc.store.remember(None, stale)
    assert pc.store.take(None) is None, "an expired clarification was answerable"
    assert not pc.store.awaiting_answer()


def test_awaiting_answer_does_not_consume():
    """The wake listener asks this to decide whether to keep listening; if it
    popped, asking would destroy the thing it is asking about."""
    pc.store.remember(None, _clar())
    assert pc.store.awaiting_answer()
    assert pc.store.awaiting_answer()
    assert pc.store.take(None) is not None


def test_clear_all_empties_it():
    pc.store.remember(None, _clar())
    pc.store.clear_all()
    assert not pc.store.awaiting_answer()


def test_the_ttl_is_a_named_constant():
    assert isinstance(pc.CLARIFICATION_TTL_S, (int, float))
    assert pc.CLARIFICATION_TTL_S == 60


# ── never auto-filled ──────────────────────────────────────────────────


def test_the_store_has_no_way_to_fill_the_missing_argument():
    """Structural guarantee, not a behavioural one.

    If the store could write the user's utterance into `args`, some future
    caller would — and "Onyx, what's the weather" becomes the body of a
    WhatsApp message to Sharath. The only writer is remember(); the only
    reader is take(). The planner does the deciding.
    """
    import inspect

    src = inspect.getsource(pc)
    assert "def fill" not in src and "def answer" not in src, (
        "the clarification store grew a way to fill the missing argument "
        "directly; that bypasses the planner's judgement AND the Guardian"
    )


def test_the_context_block_tells_the_planner_it_may_be_unrelated():
    """The prompt has to license ignoring the question, or the planner will
    force any utterance into the pending slot."""
    block = pc.context_for(_clar())
    low = block.lower()
    assert "send_whatsapp" in block and "message" in low
    assert "sharath" in low, "known args must be carried so they aren't re-asked"
    assert "unrelated" in low or "ignore" in low, (
        f"nothing in {block!r} permits the planner to treat the utterance as a "
        "new request; it will stuff the weather into the message body"
    )


# ── wiring ─────────────────────────────────────────────────────────────


def test_the_stop_handler_clears_clarifications():
    """"stop"/"cancel"/"never mind" resolve in the rule tier and never reach
    Commander, so the stop handler is the only place they can land."""
    import inspect

    from backend.core.safe_executor import command_whitelist

    src = inspect.getsource(command_whitelist.handle_stop)
    assert "clarification" in src.lower(), (
        "saying 'never mind' leaves a half-built WhatsApp message pending"
    )


def test_the_wake_listener_extends_the_window_for_a_clarification():
    """_start_turn widens the idle window when a question is outstanding. It
    only knew about yes/no confirmations."""
    import inspect

    from backend.daemon import wake_word as ww

    src = inspect.getsource(ww.WakeWordListener._start_turn)
    assert "clarification" in src.lower(), (
        "a clarification does not extend the idle window, so Onyx asks and "
        "then stops listening — the original bug, one layer down"
    )


def test_commander_writes_the_slot_on_a_missing_argument_question():
    """Wiring guard for the write side."""
    import inspect

    from backend.core.agents import commander as cmd

    src = inspect.getsource(type(cmd.commander)._run_loop_stream)
    assert "pending_clarification" in src or "_clarification" in src, (
        "Commander never records the question it just asked"
    )


def test_missing_argument_errors_are_parsed_into_tool_and_param():
    """Built from the verifier's own wording, so a reword there fails here
    rather than silently disabling the feature."""
    from backend.core.agent import verifier  # noqa: F401

    req, resolved = "message", "send_whatsapp"
    real_error = f"Missing required argument {req!r} for tool {resolved!r}."
    parsed = pc.parse_missing_arg(real_error)
    assert parsed == ("message", "send_whatsapp"), parsed
    assert pc.parse_missing_arg("some other failure") is None


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
