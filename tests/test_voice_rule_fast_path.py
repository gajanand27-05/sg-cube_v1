"""The voice path never consulted the cache or the rule tier.

The HUD shows CACHE 0 / RULE 0 / LLM n and it is not a display bug: the voice
path goes trigger -> Brain -> Commander, and Brain builds a RequestContext and
calls Commander directly. trigger.py said so in a comment while publishing
IntentResolved: "Voice path bypasses the router ... source_layer is always
'llm' since voice goes straight to the planner."

Two consequences, one slow and one broken:

  * Measured over 838 real commands from this machine's timeline, 143 (17.1%)
    match a rule at 0.009ms each, against a measured planner first-token of
    ~2300ms. 126 of those are "what time is it" — the single most common
    thing said to this assistant, paying a cloud round-trip to read the clock.

  * "stop" is deliberately a rule and not a tool (handle_stop: a tool call
    would wait on the planner, and a stop that waits on a model is not a
    stop). Because voice skipped the rule tier, spoken "stop" reached the
    planner, which has no stop capability. That is why stop did not work by
    voice.

The fast path is deliberately NOT all 143 hits. Rules act literally where the
planner declines, and two of those hits are mis-transcriptions a rule would
execute — 'No.1.2.2.9.9.9.9.9.9.9.9' matches open_url, '1-0.' matches
calculate. Read-only and safety-critical actions only.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon import trigger
from backend.daemon.trigger import _VOICE_FAST_PATH_ACTIONS, _try_rule_fast_path


class _Turn:
    def mark(self, _name):
        pass


def _run(command, spoken_spy=None):
    async def go():
        with patch.object(trigger, "_speak_selective", spoken_spy or _noop_speak), \
             patch.object(trigger, "get_bus"), \
             patch.object(trigger, "latency_ledger"), \
             patch.object(trigger, "state_manager"):
            return await _try_rule_fast_path(command, None, _Turn())
    return asyncio.run(go())


async def _noop_speak(text, device_id=None):
    return None


# ── what the fast path covers ──────────────────────────────────────────

def test_the_most_common_command_skips_the_planner():
    """126 of 838 real commands. This is the whole latency win."""
    said = []

    async def spy(text, device_id=None):
        said.append(text)

    assert _run("what time is it", spy) is True
    assert said, "the time was resolved but never spoken"
    assert any(ch.isdigit() for ch in said[0]), f"expected a clock reading, got {said[0]!r}"


def test_stop_reaches_the_rule_engine_by_voice():
    """Correctness, not latency. Spoken "stop" used to reach the planner."""
    with patch("backend.core.safe_executor.command_whitelist.handle_stop") as h:
        h.return_value = {"status": "success", "message": ""}
        # HANDLERS captured the function at import, so patch the table entry.
        with patch.dict("backend.core.safe_executor.command_whitelist.HANDLERS",
                        {"stop": h}):
            assert _run("stop") is True
    assert h.called, "spoken 'stop' did not reach handle_stop"


def test_stop_says_nothing():
    """handle_stop returns an empty message on purpose — speaking "Done" is
    the one thing the user just asked us not to do."""
    said = []

    async def spy(text, device_id=None):
        said.append(text)

    _run("stop", spy)
    assert said == [], f"stop spoke {said!r}"


# ── what it deliberately does NOT cover ────────────────────────────────

def test_side_effecting_rules_still_go_to_the_planner():
    """These match a rule, but a rule executes literally where the planner
    declines. They must fall through so the verifier and the confirmation
    gate still apply."""
    for command in ["open chrome", "close notepad", "play nato",
                    "translate this to spanish"]:
        assert _run(command) is None, command


def test_the_real_mis_transcriptions_that_would_have_been_executed():
    """Verbatim from the timeline. Both match a rule; neither is a command.
    Routing all rule hits to the fast path would have executed these."""
    for command in ["No.1.2.2.9.9.9.9.9.9.9.9", "1-0."]:
        assert _run(command) is None, command


def test_a_normal_question_is_untouched():
    for command in ["what is the capital of France", "read the text on my screen",
                    "how many moons does mars have"]:
        assert _run(command) is None, command


def test_the_allowlist_contains_nothing_that_acts_on_the_world():
    """Guard on the list itself. Adding open_app or delete_file here would
    hand a mis-transcription a direct, unverified route to execution."""
    assert _VOICE_FAST_PATH_ACTIONS == {"get_time", "stop"}, (
        "the voice fast path skips the verifier and the confirmation gate, so "
        "every action on it must be read-only or a safety control"
    )


def test_a_broken_handler_falls_back_to_the_planner():
    """The fast path must never be able to break a turn — before it existed,
    everything went to the planner, and that is the failure mode."""
    def boom(_intent):
        raise RuntimeError("handler exploded")

    with patch.dict("backend.core.safe_executor.command_whitelist.HANDLERS",
                    {"get_time": boom}):
        assert _run("what time is it") is None


def test_it_is_wired_before_brain():
    """Wiring guard. Computing the fast path after the planner call would
    save nothing at all."""
    import inspect
    src = inspect.getsource(trigger._process_and_execute)
    assert "_try_rule_fast_path" in src
    assert src.index("_try_rule_fast_path") < src.index("BrainRequest("), (
        "the fast path runs after the Brain request is built, so it cannot "
        "be avoiding any planner work"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
