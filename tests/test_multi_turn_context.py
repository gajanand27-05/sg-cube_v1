"""Multi-turn conversation regression — see T-planner-turn-stale.

The bug: Commander snapshotted `recent_conversation` BEFORE adding the current
turn, and the Planner only appended `user_query` when history was empty. So
from turn 2 onward the current question never reached the model and the
assistant answered the PREVIOUS question:

    Q: what is the capital of France   -> A: Paris                  (correct)
    Q: what is the tallest mountain    -> A: Paris                  (WRONG)
    Q: how many legs does a spider     -> A: ... Mount Everest ...   (WRONG)

Turn 1 worked because empty history hit the `else` branch, which is exactly
why 200 single-shot tests never caught it. Every test here is deliberately
multi-turn.

The load-bearing assertion is inside the mock: it checks that the messages
the Planner actually sends END with the current question. A mock that only
returned a canned string would pass even with the bug present.
"""
import json
from dataclasses import dataclass, field

import pytest

from backend.core.agent.context import ConversationContext
from backend.core.context.types import AgentContext


QUESTIONS = [
    "what is the capital of France",
    "what is the tallest mountain in the world",
    "how many legs does a spider have",
]


@dataclass
class _Capture:
    """Records what the Planner sent to the LLM on each turn."""
    calls: list[list[dict]] = field(default_factory=list)


class _FakeProvider:
    """Stands in for LLMProvider.

    Asserts the contract that actually matters: the final user message must be
    the question being asked right now. Then answers with that question echoed
    back, so the caller can prove the answer matches its own question.
    """

    def __init__(self, capture: _Capture, expected_query_for_call):
        self._capture = capture
        self._expected = expected_query_for_call

    async def chat_stream(self, messages, **kwargs):
        self._capture.calls.append(list(messages))
        expected = self._expected(len(self._capture.calls) - 1)

        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert user_msgs, "Planner sent no user message at all"
        assert user_msgs[-1]["content"] == expected, (
            "Planner did not send the CURRENT question. "
            f"expected last user message {expected!r}, "
            f"got {user_msgs[-1]['content']!r}. "
            f"full user messages: {[m['content'] for m in user_msgs]}"
        )

        payload = json.dumps({"final_response": f"ANSWER::{expected}"})
        yield {"token": payload, "done": False}
        yield {"token": "", "done": True}


@pytest.fixture
def patched(monkeypatch):
    """Wire the Planner to the fake provider and stub out context building."""
    from backend.core.agents import planner as planner_mod
    from backend.core.agents import commander as commander_mod

    capture = _Capture()
    provider = _FakeProvider(capture, lambda i: QUESTIONS[i])
    monkeypatch.setattr(planner_mod, "get_provider", lambda: provider)

    async def _fake_collect(request):
        return AgentContext(
            user_intent=request.user_intent,
            input_mode=request.input_mode,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    monkeypatch.setattr(commander_mod.context_builder, "collect", _fake_collect)
    monkeypatch.setattr(
        commander_mod.timeline, "record_event", lambda **kw: None
    )

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(
        commander_mod.episodic_summarizer, "summarize_and_store", _noop
    )
    return capture


@pytest.mark.asyncio
async def test_each_turn_answers_its_own_question(patched):
    """Three sequential turns on ONE context: no answer may lag a turn."""
    from backend.core.agents.commander import CommanderAgent

    agent = CommanderAgent()
    context = ConversationContext()

    answers = []
    for q in QUESTIONS:
        spoken, _tools = await agent.run(q, context)
        answers.append(spoken)

    for q, a in zip(QUESTIONS, answers):
        assert a == f"ANSWER::{q}", (
            f"answer lagged: question {q!r} produced {a!r}"
        )


@pytest.mark.asyncio
async def test_history_grows_and_includes_current_turn(patched):
    """Turn N must see turns 1..N-1 AND its own question."""
    from backend.core.agents.commander import CommanderAgent

    agent = CommanderAgent()
    context = ConversationContext()
    for q in QUESTIONS:
        await agent.run(q, context)

    # Turn 1 sends only its own question; later turns carry the ones before.
    first_turn_users = [
        m["content"] for m in patched.calls[0] if m["role"] == "user"
    ]
    assert first_turn_users == [QUESTIONS[0]]

    third_turn_users = [
        m["content"] for m in patched.calls[2] if m["role"] == "user"
    ]
    for q in QUESTIONS:
        assert q in third_turn_users, f"{q!r} missing from turn 3 history"
    assert third_turn_users[-1] == QUESTIONS[2]


@pytest.mark.asyncio
async def test_planner_appends_query_when_history_omits_it(patched):
    """Defensive path: a caller passing prior-only history still works.

    Commander is the source of truth and puts the current turn in history,
    but the Planner must not silently drop the question if some other caller
    doesn't — that is the exact shape of the original bug.
    """
    from backend.core.agents.planner import PlannerAgent

    agent = PlannerAgent()
    ctx = AgentContext(user_intent=QUESTIONS[0])
    stale_history = [
        {"role": "user", "content": "an older unrelated question"},
        {"role": "assistant", "content": "an older answer"},
    ]

    async for _chunk in agent.generate_plan_stream(QUESTIONS[0], stale_history, ctx):
        pass

    sent = patched.calls[-1]
    user_msgs = [m["content"] for m in sent if m["role"] == "user"]
    assert user_msgs[-1] == QUESTIONS[0]
    assert "an older unrelated question" in user_msgs


@pytest.mark.asyncio
async def test_planner_does_not_duplicate_query_already_in_history(patched):
    """Commander's history already ends with the question — don't append twice."""
    from backend.core.agents.planner import PlannerAgent

    agent = PlannerAgent()
    ctx = AgentContext(user_intent=QUESTIONS[0])
    history = [{"role": "user", "content": QUESTIONS[0]}]

    async for _chunk in agent.generate_plan_stream(QUESTIONS[0], history, ctx):
        pass

    sent = patched.calls[-1]
    occurrences = sum(
        1 for m in sent if m["role"] == "user" and m["content"] == QUESTIONS[0]
    )
    assert occurrences == 1, f"question duplicated {occurrences}x in prompt"
