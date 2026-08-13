"""Trusted system-write tools must still confirm when the turn wasn't addressed to us.

Shipped in 2c3ba00 across six files with no test at all — which is a poor state
for a gate that decides whether an action runs WITHOUT asking the user.

The threat it closes (T-wake-word-executes-ambient-audio): the follow-up window
and barge-in both trigger on ambient sound, not on the wake word. A
mis-transcription there could execute any tool on the trusted allowlist while
the user never addressed the assistant at all. So `trusted` is honoured only
when the turn began with an explicit wake, or came in by text (no voice trigger
at all); every other origin falls through to the deep check and a confirmation
prompt.

Both directions matter and both are asserted here. Too permissive is the
vulnerability. Too strict makes every follow-up demand confirmation, which
trains the user to say yes without reading — and that is how a confirmation
prompt stops being a safeguard.

The trigger source lives in a module global set by wake_word.py and cleared by
trigger.py, so leakage between turns is the obvious failure mode; it gets its
own test.
"""
import asyncio
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.agent import verifier as v
from backend.core.agent.verifier import verify
from backend.core.state import manager as state_manager
from backend.core.tools.registry import REGISTRY, CapabilityTier, ToolResult, tool

TOOL_NAME = "_gate_stub_trusted_write"


@pytest.fixture(autouse=True)
def stub_secondary_check(monkeypatch):
    """_secondary_check makes a live LLM call. Stub it to PASS, so anything the
    gate lets through to it is visible as needs_confirmation rather than as a
    rejection caused by an unreachable Ollama."""
    async def _pass(*_a, **_kw):
        return True
    monkeypatch.setattr(v, "_secondary_check", _pass)


@pytest.fixture()
def trusted_write_tool():
    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
    def _gate_stub_impl() -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

    REGISTRY[TOOL_NAME] = REGISTRY.pop("_gate_stub_impl")
    REGISTRY[TOOL_NAME].name = TOOL_NAME
    REGISTRY[TOOL_NAME].schema["name"] = TOOL_NAME
    yield TOOL_NAME
    REGISTRY.pop(TOOL_NAME, None)


@pytest.fixture(autouse=True)
def clean_trigger_source():
    original = state_manager._voice_trigger_source
    yield
    state_manager._voice_trigger_source = original


def _verify(name):
    return asyncio.run(verify(user_query="do the thing", call={
        "name": name, "args": {}, "reasoning": "test", "confidence": 1.0,
    }))


@pytest.mark.parametrize("source", ["wake", None])
def test_an_explicitly_addressed_turn_runs_without_confirmation(trusted_write_tool, source):
    """"wake" is the user saying the wake word; None is the text path, where
    there is no ambient audio to mis-hear. Both are unambiguous intent."""
    state_manager._voice_trigger_source = source
    res = _verify(trusted_write_tool)

    assert res.is_valid is True, res.error
    assert res.needs_confirmation is False, (
        f"trigger_source={source!r} is an explicit request; demanding "
        "confirmation here trains the user to click yes without reading"
    )


@pytest.mark.parametrize("source", ["followup", "barge_in"])
def test_an_ambient_turn_still_has_to_ask(trusted_write_tool, source):
    """The actual vulnerability. Both of these fire on sound, not on the wake
    word, so the user may never have addressed the assistant."""
    state_manager._voice_trigger_source = source
    res = _verify(trusted_write_tool)

    assert res.is_valid is True, res.error
    assert res.needs_confirmation is True, (
        f"a trusted system-write ran unconfirmed on a {source!r} turn — a "
        "mis-transcribed ambient word could trigger it with the user unaware"
    )


def test_an_unknown_trigger_source_fails_closed(trusted_write_tool):
    """A new trigger kind added to wake_word.py must not silently inherit the
    bypass. The gate lists what is trusted rather than what is not."""
    state_manager._voice_trigger_source = "some_future_trigger"
    assert _verify(trusted_write_tool).needs_confirmation is True


def test_the_trigger_source_does_not_leak_into_the_next_turn():
    """It is a module global written by wake_word.py and cleared in trigger.py's
    finally block. If that clear were dropped, one barge-in would make every
    later turn — including typed ones — demand confirmation forever."""
    import inspect

    from backend.daemon import trigger

    source = inspect.getsource(trigger._handle_wake_async)
    assert "_voice_trigger_source = None" in source, (
        "trigger.py no longer clears the trigger source; it will persist into "
        "unrelated later turns"
    )
    assert source.index("finally:") < source.index("_voice_trigger_source = None"), (
        "the clear must be in the finally block, or an exception mid-turn "
        "leaves the previous trigger source armed"
    )


def test_an_untrusted_system_write_always_confirms(clean_trigger_source):
    """The trust flag is what the trigger source gates. Without trust, even an
    explicit wake must confirm — otherwise this test would pass for the wrong
    reason above."""
    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=False)
    def _gate_stub_untrusted() -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

    name = "_gate_stub_untrusted_write"
    REGISTRY[name] = REGISTRY.pop("_gate_stub_untrusted")
    REGISTRY[name].name = name
    REGISTRY[name].schema["name"] = name
    try:
        state_manager._voice_trigger_source = "wake"
        assert _verify(name).needs_confirmation is True
    finally:
        REGISTRY.pop(name, None)
