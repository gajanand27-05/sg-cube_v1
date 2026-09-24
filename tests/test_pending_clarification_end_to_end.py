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
            -> must complete the ORIGINAL send_whatsapp.

send_whatsapp was DESTRUCTIVE and so completed behind a spoken confirmation.
Since 2026-09-24 it is trusted: it only opens a pre-filled draft, and nothing
is sent until the user presses Send in WhatsApp (nothing in backend/ presses
it). So completing it now means opening exactly that draft for exactly that
recipient — which is what these tests pin.

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


@pytest.fixture
def opened(monkeypatch):
    """Record the draft the tool opens instead of opening a real browser, and
    give the (isolated) contact book the recipient the scenario names."""
    from backend.core.contacts import book
    from backend.core.tools import comms

    book.add("Sharath", "+919876543210")
    urls = []
    monkeypatch.setattr(comms.webbrowser, "open", urls.append)
    yield urls
    book.delete("Sharath")


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
DONE = {"final_response": "Opened WhatsApp with your message."}
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


def test_the_answer_after_a_fresh_wake_completes_the_action(opened):
    """The regression. Turn 2 is a SEPARATE run_stream call with its own
    context object — the chain died in between, exactly as in the log."""
    first = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(first, "to send a whatsapp message to sharat")
    assert pc.store.awaiting_answer(), "fixture precondition"

    second = _ScriptedPlanner([COMPLETED, DONE])
    chunks = _run(second, "the message is hi sharath how are you doing")

    shown = "\n".join(m["content"] for m in second.seen_history[0])
    assert "pending question" in shown.lower(), (
        "the planner was never told a question was outstanding, so it had no "
        "way to know this utterance was an answer"
    )
    assert "Sharath" in shown, "known args were not carried into the prompt"

    assert len(opened) == 1 and "wa.me/919876543210" in opened[0], (
        f"the original send_whatsapp never completed: {opened!r}")


def test_the_draft_carries_exactly_what_was_said(opened):
    """The safety net moved from a spoken read-back to the draft itself: the
    user sees these exact words in WhatsApp before pressing Send."""
    first = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(first, "to send a whatsapp message to sharat")
    _run(_ScriptedPlanner([COMPLETED, DONE]),
         "the message is hi sharath how are you doing")

    from urllib.parse import parse_qs, urlparse

    assert len(opened) == 1, opened
    text = parse_qs(urlparse(opened[0]).query)["text"][0]
    assert text == "Hi Sharath, how are you doing?", text


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


def test_a_recovered_turn_does_not_leave_a_phantom_question():
    """Found in review of the pushed main.

    `unfilled` is set when the Guardian rejects a call for a missing argument
    and is never cleared. It is read much later, in the final_response branch
    — and a turn that RECOVERED reaches that same branch, because the
    multi-tool assessment loop comes back around to the planner.

    A single successful tool hides this: that path returns early at
    `if len(batch_results) == 1`. Two or more tools fall through, iterate, and
    the planner's closing sentence lands on the write site:

        planner: send_whatsapp{contact}  -> Guardian rejects 'message'
                 [get_time, get_time]    -> executes
                 final_response "It is 9:15 PM."
        stored:  Clarification(tool='send_whatsapp', missing='message',
                               question='It is 9:15 PM.')

    So an ordinary recovered turn leaves a pending question pointing at a
    DESTRUCTIVE tool, carrying its own ANSWER as the question it supposedly
    asked. The next turn is then told Onyx asked "It is 9:15 PM." and that
    send_whatsapp is missing its message.

    The read-back confirmation does stop it sending — that precondition
    earning its keep — but the slot should never have been written. Only a
    rejection FOLLOWED BY A QUESTION may write it.
    """
    two_tools = {"tool_calls": [{"name": "get_time", "args": {}},
                                {"name": "get_time", "args": {}}]}
    planner = _ScriptedPlanner([INCOMPLETE, two_tools,
                                {"final_response": "It is 9:15 PM."}])
    chunks = _run(planner, "what time is it")

    assert "9:15" in _spoken(chunks), _spoken(chunks)
    assert not pc.store.awaiting_answer(), (
        "a recovered turn stored a phantom clarification: "
        f"{pc.store.take(None)!r} — its 'question' is this turn's answer, and "
        "the next turn will be told a DESTRUCTIVE send is half-built"
    )


def test_a_later_rejection_for_another_reason_clears_the_half_built_call():
    """The second route, found by checking rather than assuming — and it is a
    DIFFERENT mechanism, not the same one.

    Clearing `unfilled` once the Guardian passes does not cover this: the
    Guardian never passes. A missing-argument rejection sets `unfilled`, then
    a rejection for an unrelated reason ("Tool 'x' not found in registry.")
    leaves it standing, and the eventual closing sentence writes it.

    Arguably the likelier of the two in practice: a planner that is flailing
    produces several different errors in a row, not one.

    So `unfilled` must describe the most recent rejection and nothing else.
    """
    two_tools = {"tool_calls": [{"name": "get_time", "args": {}},
                                {"name": "no_such_tool_at_all", "args": {}}]}
    planner = _ScriptedPlanner([INCOMPLETE, two_tools,
                                {"final_response": "I couldn't do that."}])
    _run(planner, "what time is it")

    assert not pc.store.awaiting_answer(), (
        f"a failed recovery stored a phantom clarification: {pc.store.take(None)!r}"
    )


def test_a_genuine_question_still_writes_the_slot():
    """Guard against fixing this by never writing the slot at all."""
    planner = _ScriptedPlanner([INCOMPLETE, QUESTION])
    _run(planner, "to send a whatsapp message to sharat")
    assert pc.store.awaiting_answer(), (
        "clearing `unfilled` went too far — a real missing-argument question "
        "no longer records what it was asking about"
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
