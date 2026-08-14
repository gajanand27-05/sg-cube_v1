"""Saying stop must stop, instantly, without asking a model.

There was no stop command anywhere — no rule, no tool. "onyx stop" silenced
the TTS only because the wake phrase itself interrupts speech; the word "stop"
then missed cache and rules, reached the LLM agent, which has no stop
capability, and the assistant started talking AGAIN seconds later. From the
user's side that is the assistant refusing a direct order.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.orchestrator import rule_engine
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw
from backend.core.safe_executor.executor import ExecutionResult
from backend.server.routes.voice import _build_spoken_response

STOP_PHRASES = [
    "stop", "stop it", "stop that", "stop talking", "stop speaking",
    "cancel", "cancel that", "never mind", "nevermind", "forget it",
    "be quiet", "quiet", "silence", "shut up", "abort", "enough", "wait",
]


@pytest.mark.parametrize("phrase", STOP_PHRASES)
def test_stop_phrases_resolve_without_a_model(phrase):
    """Rule layer only. A stop that waits on the planner is not a stop."""
    intent = rule_engine.match(phrase)
    assert intent is not None, f"{phrase!r} falls through to the LLM agent"
    assert intent.action == "stop", f"{phrase!r} resolved to {intent.action!r}"


@pytest.mark.parametrize("phrase,would_have_been", [
    ("stop playing music", "play_youtube"),   # eaten by ^play (.+)$
    ("stop", "search_google"),                # nothing matched -> agent
])
def test_stop_wins_over_the_catch_all_rules(phrase, would_have_been):
    """RULES is ordered; the search and play catch-alls sit near the bottom
    and would otherwise swallow these."""
    intent = rule_engine.match(phrase)
    assert intent is not None and intent.action == "stop", (
        f"{phrase!r} was captured by the {would_have_been!r} catch-all"
    )


def test_stop_is_dispatchable():
    """A rule that produces an action with no HANDLERS entry returns
    status='blocked: unknown action' — a silent no-op from the user's side."""
    assert "stop" in cw.HANDLERS


def test_stop_interrupts_speech_queue_and_agent(monkeypatch):
    """All three, not just the loudest one. Speech alone leaves the queued
    sentences to resume; the queue alone leaves the agent still working."""
    called = []
    monkeypatch.setattr("backend.ai_modules.speech.tts_piper.stop_speech",
                        lambda: called.append("speech"))

    class _Q:
        def interrupt(self): called.append("queue")

    monkeypatch.setattr("backend.ai_modules.speech.tts_queue.get_sentence_queue",
                        lambda: _Q())
    monkeypatch.setattr("backend.core.agents.commander.commander.interrupt",
                        lambda: called.append("agent"))

    res = cw.handle_stop(Intent(action="stop", target=""))
    assert res["status"] == "success"
    assert set(called) == {"speech", "queue", "agent"}, called


def test_one_failing_interrupt_does_not_block_the_others(monkeypatch):
    """The whole point of a stop is that it stops. A raising TTS handle must
    not leave the agent running."""
    called = []

    def boom():
        raise RuntimeError("audio device gone")

    monkeypatch.setattr("backend.ai_modules.speech.tts_piper.stop_speech", boom)

    class _Q:
        def interrupt(self): called.append("queue")

    monkeypatch.setattr("backend.ai_modules.speech.tts_queue.get_sentence_queue",
                        lambda: _Q())
    monkeypatch.setattr("backend.core.agents.commander.commander.interrupt",
                        lambda: called.append("agent"))

    res = cw.handle_stop(Intent(action="stop", target=""))
    assert res["status"] == "success"
    assert set(called) == {"queue", "agent"}, called


def test_stop_answers_with_silence():
    """Answering "Done" out loud is the one thing the user just asked us not
    to do."""
    spoken = _build_spoken_response(
        Intent(action="stop", target=""),
        ExecutionResult(status="success", intent=Intent(action="stop", target=""),
                        message="", latency_ms=1),
    )
    assert spoken == "", f"stop spoke {spoken!r}"


def test_ordinary_commands_are_not_swallowed_by_the_stop_rule():
    """The stop patterns are anchored; a command that merely contains one of
    those words must still work."""
    for phrase, expected in [
        ("open notepad", "open_app"),
        ("play music on youtube", "play_youtube"),
        ("search for waiting rooms", "search_google"),
    ]:
        intent = rule_engine.match(phrase)
        assert intent is not None and intent.action == expected, (
            f"{phrase!r} was captured by the stop rule"
        )
