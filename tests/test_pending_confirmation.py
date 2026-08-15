"""The confirmation gate must be answerable.

Commander asked "I need your permission to X. Should I proceed?" and then
returned, discarding the call. Nothing stored it, nothing consumed a reply, so
"yes" arrived as an unrelated new turn and the action never ran. Every
SYSTEM_WRITE tool off the trusted allowlist and every DESTRUCTIVE tool was
unreachable by voice.

The existing cover (tests/test_trigger_source_gate.py) asserts the gate FIRES.
Nothing asserted that answering it completes the action — which is why a
safeguard that could never be satisfied shipped and stayed. The round-trip
test at the bottom is the one that would have caught it.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.pending_confirmation import (
    Pending,
    PendingStore,
    classify_reply,
)


# ── reply classification ───────────────────────────────────────────────

def test_affirmations_are_recognised():
    for t in ["yes", "Yes.", "yeah", "yep", "sure", "ok", "okay", "OK!",
              "proceed", "go ahead", "do it", "confirm", "please do",
              "alright", "yes please", "go for it"]:
        assert classify_reply(t) == "yes", repr(t)


def test_negations_are_recognised():
    for t in ["no", "No.", "nope", "nah", "no thanks", "don't", "forget it"]:
        assert classify_reply(t) == "no", repr(t)


def test_a_new_request_is_not_an_answer():
    """The dangerous direction. Anything that is not plainly yes/no must read
    as a new instruction, or the user's next sentence silently authorises
    whatever was pending."""
    for t in [
        "yes but play something else",      # contains "yes" — still a new ask
        "no, open notepad instead",
        "what time is it",
        "play some music on youtube",
        "okay so what about the weather",
        "",
        "   ",
    ]:
        assert classify_reply(t) is None, repr(t)


def test_stop_words_are_not_classified_here():
    """"cancel"/"stop"/"never mind"/"abort" resolve to the stop command in the
    rule tier and never reach Commander. Claiming them here would imply cover
    that does not exist — handle_stop clears the store instead."""
    for t in ["cancel", "stop", "never mind", "abort"]:
        assert classify_reply(t) is None, repr(t)


# ── the store ──────────────────────────────────────────────────────────

def _pending(name="play youtube"):
    return Pending(calls=[{"name": "play_youtube", "args": {}}],
                   user_query="play music", tool_name=name)


def test_take_pops_so_a_prompt_cannot_be_answered_twice():
    store = PendingStore()
    store.remember("s1", _pending())
    assert store.take("s1") is not None
    assert store.take("s1") is None


def test_take_pops_even_when_the_answer_is_unrelated():
    """The load-bearing rule. If an unanswered prompt survived, a "sure" three
    turns later — meant for something else entirely — would authorise it."""
    store = PendingStore()
    store.remember("s1", _pending())
    taken = store.take("s1")          # caller sees "what time is it", drops it
    assert taken is not None
    assert store.take("s1") is None   # gone regardless of what the caller did


def test_expiry():
    """Age the pending rather than zeroing the TTL: at ttl=0 the elapsed time
    can round to exactly 0.0, and `elapsed > ttl` is then false — the test
    would pass or fail on clock resolution instead of on the rule."""
    import time as _time
    from backend.server.config import settings
    store = PendingStore()
    p = _pending()
    p.created_at = _time.monotonic() - (settings.confirmation_ttl_s + 1.0)
    store.remember("s1", p)
    assert store.take("s1") is None


def test_not_yet_expired_still_answerable():
    store = PendingStore()
    store.remember("s1", _pending())
    assert store.take("s1") is not None


def test_sessions_do_not_leak_into_each_other():
    store = PendingStore()
    store.remember("s1", _pending("play youtube"))
    store.remember("s2", _pending("delete file"))
    assert store.take("s2").tool_name == "delete file"
    assert store.take("s1").tool_name == "play youtube"


def test_second_prompt_replaces_the_first():
    """One slot. A queue of half-authorised actions is worse than forgetting."""
    store = PendingStore()
    store.remember("s1", _pending("play youtube"))
    store.remember("s1", _pending("delete file"))
    assert store.take("s1").tool_name == "delete file"
    assert store.take("s1") is None


def test_clear_all():
    store = PendingStore()
    store.remember("s1", _pending())
    store.remember("s2", _pending())
    store.clear_all()
    assert store.take("s1") is None and store.take("s2") is None


# ── round trip through the real Commander ──────────────────────────────

class _FakeContext:
    def __init__(self):
        self.session_id = "test-session"
        self.turns = []

    def add_user(self, t):
        self.turns.append(("user", t))

    def add_assistant(self, t):
        self.turns.append(("assistant", t))

    def render(self):
        return [{"role": r, "content": c} for r, c in self.turns]


class _Res:
    def __init__(self, status="success", message="Playing Lo-fi beats"):
        self.status = status
        self.message = message


def _drive(commander, text, ctx):
    """Run one Commander turn to completion, returning the spoken reply."""
    async def go():
        spoken = None
        async for chunk in commander._run_loop_stream(text, ctx, "u1"):
            if chunk.type == "final_response":
                spoken = chunk.content
        return spoken
    return asyncio.run(go())


def _commander_asking_permission(executed):
    """A Commander whose planner proposes play_youtube and whose guardian
    holds it pending — the exact state the user hit."""
    from backend.core.agents.commander import CommanderAgent

    call = {"name": "play_youtube", "args": {"query": "lofi"}, "is_critical": False}

    async def fake_plan(text, history, ctx):
        # Only a music request proposes the tool. A planner that proposed it
        # for every input would silently re-create the pending on the
        # unrelated-turn test and hide the very thing that test checks.
        if "music" in text.lower() or "play" in text.lower():
            yield {"type": "final", "content": {"tool_calls": [call]}}
        else:
            yield {"type": "final", "content": {"final_response": "It is 3pm."}}

    async def fake_verify(text, calls, request_id, agent_context):
        return [], [call], []          # nothing valid, one pending, no errors

    async def fake_execute(calls, request_id):
        executed.extend(calls)
        return [{"tool": "play_youtube", "result": _Res()}]

    c = CommanderAgent()
    c.planner.generate_plan_stream = fake_plan
    c.guardian.verify_plan = fake_verify
    c.operator.execute_batch = fake_execute
    return c


@pytest.fixture
def quiet_commander():
    """Silence the side channels Commander touches on every turn."""
    with patch("backend.core.agents.commander.context_builder") as cb, \
         patch("backend.core.agents.commander.timeline"), \
         patch("backend.core.agents.commander.get_bus"), \
         patch("backend.core.agents.commander.episodic_summarizer") as summ:
        class _Ctx:
            request_id = "req1"
            recent_conversation = []
        async def collect(_req):
            return _Ctx()
        cb.collect = collect
        # The final_response branch does asyncio.create_task(...) on this, so
        # it has to hand back a real coroutine, not a MagicMock.
        async def _noop(*a, **kw):
            return None
        summ.summarize_and_store = _noop
        yield


def test_saying_yes_actually_runs_the_action(quiet_commander):
    """The round trip nobody tested. Ask → 'proceed' → the tool runs."""
    from backend.core.agents.pending_confirmation import store
    store.clear_all()
    executed = []
    c = _commander_asking_permission(executed)
    ctx = _FakeContext()

    asked = _drive(c, "play some music on youtube", ctx)
    assert "permission" in asked.lower(), asked
    assert executed == [], "must not run before the user answers"

    spoken = _drive(c, "proceed", ctx)
    assert len(executed) == 1, "saying yes did not execute the pending call"
    assert executed[0]["name"] == "play_youtube"
    assert spoken == "Playing Lo-fi beats", spoken


def test_saying_no_cancels_and_does_not_run(quiet_commander):
    from backend.core.agents.pending_confirmation import store
    store.clear_all()
    executed = []
    c = _commander_asking_permission(executed)
    ctx = _FakeContext()

    _drive(c, "play some music on youtube", ctx)
    spoken = _drive(c, "no", ctx)
    assert executed == []
    assert "won't" in spoken.lower(), spoken


def test_an_unrelated_next_turn_discards_the_pending(quiet_commander):
    """The user moved on. The action must not run now, and must not be
    sitting there to run on a later 'sure'."""
    from backend.core.agents.pending_confirmation import store
    store.clear_all()
    executed = []
    c = _commander_asking_permission(executed)
    ctx = _FakeContext()

    _drive(c, "play some music on youtube", ctx)
    _drive(c, "what time is it", ctx)          # falls through to planning
    assert executed == []
    assert store.take("test-session") is None, "pending survived an unrelated turn"


def test_failure_is_reported_not_claimed(quiet_commander):
    """If the authorised action fails, say so. Claiming success is the exact
    failure mode the confirmation exists to prevent."""
    from backend.core.agents.commander import _confirmed_summary
    out = _confirmed_summary(
        [{"tool": "play_youtube", "result": _Res("error", "no browser")}],
        "play youtube",
    )
    assert "failed" in out.lower() and "no browser" in out


def test_stop_clears_a_pending_confirmation():
    """"cancel"/"never mind" resolve to the stop command in the rule tier, so
    handle_stop is the only place they can clear the slot."""
    from backend.core.agents.pending_confirmation import store
    from backend.core.safe_executor.command_whitelist import handle_stop
    from backend.core.orchestrator.llm_layer import Intent

    store.clear_all()
    store.remember("s1", _pending())
    with patch("backend.ai_modules.speech.tts_piper.stop_speech"), \
         patch("backend.ai_modules.speech.tts_queue.get_sentence_queue"), \
         patch("backend.core.agents.commander.commander"):
        handle_stop(Intent(action="stop", target=""))
    assert store.take("s1") is None, "stop left an action awaiting authorisation"


def test_play_youtube_is_trusted():
    """It opens a browser tab, exactly like open_app which is trusted. Being
    off the allowlist is what made 'play some music' prompt at all."""
    from backend.core.tools.registry import CapabilityTier, REGISTRY
    tool = REGISTRY.get("play_youtube")
    assert tool is not None
    assert getattr(tool, "trusted", False) is True
    assert getattr(tool, "tier", None) == CapabilityTier.SYSTEM_WRITE


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__code__.co_argcount == 0:
            fn()
            print(f"  [PASS] {name}")
