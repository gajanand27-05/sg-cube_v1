"""The WhatsApp turn, driven through the real Commander loop.

tests/test_pending_clarification.py pins the slot and the wiring. This file
pins that the wiring FIRES — the distinction that matters, because a grep for
a symbol proves the symbol is present, not that the path executes.

Reconstructed from the live log, in two turns with a dead chain between them:

    turn 1  'to send a whatsapp message to sharat'
            -> Guardian: Missing required argument 'message'
            -> planner asks "What would you like the message to say?"
    turn 2  (chain expired, fresh wake word)
            'the message is hi sharath how are you doing'
            -> must complete the ORIGINAL send_whatsapp, still confirming.

Only the planner is stubbed. The Guardian, the self-healer, the clarification
store and the confirmation prompt are all real.
"""
import asyncio
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.agent import verifier as v
from backend.core.agents import commander as cmd
from backend.core.agents import pending_clarification as pc
from backend.core.agent.context import ConversationContext


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    pc.store.clear_all()

    async def _pass(*_a, **_kw):
        return True

    # The deep check makes a live LLM call; stub it to PASS so anything the
    # tier gate lets through shows up as needs_confirmation rather than as a
    # rejection caused by an unreachable Ollama.
    monkeypatch.setattr(v, "_secondary_check", _pass)
    yield
    pc.store.clear_all()


class _ScriptedPlanner:
    """Emits whatever the scenario says, and records what it was shown."""

    def __init__(self, script):
        self.script = list(script)
        self.seen_history = []

    async def generate_plan_stream(self, text, history, agent_context):
        self.seen_history.append([dict(m) for m in history])
        yield {"type": "final", "content": self.script.pop(0)}


def _run(planner, text):
    cmd.commander.planner = planner
    ctx = ConversationContext(session_id=None)
    out = []

    async def _drive():
        async for chunk in cmd.commander.run_stream(text, ctx, "test-user"):
            out.append(chunk)

    asyncio.run(_drive())
    return out


def _spoken(chunks):
    return " ".join(str(c.content) for c in chunks
                    if getattr(c, "type", "") == "final_response")


INCOMPLETE = {"tool_calls": [{"name": "send_whatsapp",
                              "args": {"contact": "Sharath"}}]}
QUESTION = {"final_response": "What would you like the message to say?"}
COMPLETED = {"tool_calls": [{"name": "send_whatsapp",
                             "args": {"contact": "Sharath",
                                      "message": "Hi Sharath, how are you doing?"}}]}


def test_turn_one_records_the_question_it_just_asked():
    """The write side, through the real Guardian and self-healer."""
    planner = _ScriptedPlanner([INCOMPLETE, QUESTION])
    chunks = _run(planner, "to send a whatsapp message to sharat")

    assert "message" in _spoken(chunks).lower()
    assert pc.store.awaiting_answer(), (
        "Onyx asked for the message body and kept no record of having asked"
    )
    held = pc.store.take(None)
    assert held.tool == "send_whatsapp"
    assert held.args == {"contact": "Sharath"}, (
        f"the recipient was not carried forward: {held.args!r} — the user "
        "would be asked who to send it to all over again"
    )
    assert held.missing == "message"


def test_the_answer_after_a_fresh_wake_completes_the_action():
    """The regression. Turn 2 is a SEPARATE run_stream call with its own
    context object — the chain died in between, exactly as in the log."""
    first = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(first, "to send a whatsapp message to sharat")
    assert pc.store.awaiting_answer(), "fixture precondition"

    second = _ScriptedPlanner([COMPLETED])
    chunks = _run(second, "the message is hi sharath how are you doing")

    shown = "\n".join(m["content"] for m in second.seen_history[0])
    assert "pending question" in shown.lower(), (
        "the planner was never told a question was outstanding, so it had no "
        "way to know this utterance was an answer"
    )
    assert "Sharath" in shown, "known args were not carried into the prompt"

    spoken = _spoken(chunks)
    assert "permission" in spoken.lower(), (
        f"expected the confirmation prompt, got {spoken!r} — a DESTRUCTIVE "
        "send must not complete without one"
    )


def test_the_confirmation_reads_back_what_will_be_sent():
    """Fix 3's safety net. 'Yes' has to be answerable."""
    first = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(first, "to send a whatsapp message to sharat")
    chunks = _run(_ScriptedPlanner([COMPLETED]),
                  "the message is hi sharath how are you doing")

    spoken = _spoken(chunks)
    assert "Sharath" in spoken, spoken
    assert "how are you doing" in spoken.lower(), (
        f"the message body was never read back: {spoken!r} — a false wake "
        "could put words in it and 'yes' would send them"
    )


def test_the_slot_is_consumed_and_is_not_filled_by_an_unrelated_command():
    """"Onyx, what's the weather" with a WhatsApp pending must not send the
    weather to Sharath — and must not leave the question answerable either."""
    first = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(first, "to send a whatsapp message to sharat")

    unrelated = _ScriptedPlanner([{"final_response": "It's 22 degrees."}])
    chunks = _run(unrelated, "what's the weather")

    spoken = _spoken(chunks)
    assert "22 degrees" in spoken, spoken
    assert "Sharath" not in spoken and "whatsapp" not in spoken.lower(), (
        f"an unrelated command touched the pending message: {spoken!r}"
    )
    assert not pc.store.awaiting_answer(), (
        "the question survived a turn that ignored it; a later stray 'yes' "
        "or dictated sentence could still complete it"
    )


def test_a_turn_with_no_pending_question_is_unchanged():
    """Guard: the context block must not appear when nothing is pending."""
    planner = _ScriptedPlanner([{"final_response": "Hello!"}])
    _run(planner, "hello")
    shown = "\n".join(m["content"] for m in planner.seen_history[0])
    assert "pending question" not in shown.lower(), shown


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
