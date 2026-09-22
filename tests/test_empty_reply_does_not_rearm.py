"""A turn that said nothing must not hold the microphone open.

From a live dogfooding log:

    [command] 'Fair enough. Alla, alla, Google and Jetsi color look at the same thing.'
    [wake] heard followup: '[unk]' (rms=3873)
    [ai] response:  (latency: 3442ms, tools: 0)
    [wake] listening — 8s idle, 45s left in this chain

Empty spoken text, zero tools — and the follow-up window reopened for another
8 seconds anyway, so the room kept driving turns.

`_process_and_execute` ended in an unconditional `return True`. `wake_word`
reads that as `command_handled` (`_start_turn`), and `command_handled` is the
branch that chooses between `_open_followup()` and `_note_empty_capture()`.
So "the planner returned" was being treated as "the user was served", and a
turn that produced no output at all still counted as a success and re-armed
the mic. `_FOLLOWUP_MAX_EMPTY` exists precisely to end a chain that is
producing nothing; an empty reply never reached that counter.

The predicate has to be "did this turn produce anything for the user", which
is three things, not one:
  * spoken text, or
  * a tool that ran (a silent tool call is still work the user asked for), or
  * sentences already streamed to TTS — `reply` and `sq.spoke_anything` are
    alternatives at the fallback check further up, so a streamed turn whose
    final `spoken_text` came back blank did speak and must count.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.brain import BrainChunk, BrainResponse, ToolCall
from backend.core.tools.registry import ToolResult
from backend.daemon import trigger as tr
from backend.ai_modules.speech import tts_queue


class _NullBus:
    def publish(self, event, priority=None):
        pass


def _response(spoken="", tool_calls=None):
    return BrainResponse(
        spoken_text=spoken,
        intent={},
        tool_calls=tool_calls or [],
        execution_trace=[],
        latency_ms=100,
        metadata={"request_id": "empty-reply-test", "input_mode": "voice"},
    )


def _drive(response, *, stream_sentences=()):
    """Run _process_and_execute with a stubbed brain and silent TTS."""
    async def _no_speak(*_a, **_kw):
        return None

    async def _run_stream(_req):
        for sentence in stream_sentences:
            yield BrainChunk(type="tts_ready", content=sentence)
        yield BrainChunk(type="final", content=response)

    spoken_aloud = []

    async def _fake_speak_stream(text):
        spoken_aloud.append(text)
        yield b""

    with patch.object(tr, "brain") as mock_brain, \
         patch.object(tr, "_speak_selective", side_effect=_no_speak), \
         patch.object(tr.state_manager, "transition_to"), \
         patch.object(tr, "get_bus", return_value=_NullBus()), \
         patch.object(tts_queue, "speak_stream", _fake_speak_stream):
        mock_brain.run_stream = _run_stream
        handled = asyncio.run(tr._process_and_execute(
            command="whatever the room said",
            peak=0, t0=0.0, emit=None, device_id=None,
        ))
    return handled, spoken_aloud


def test_an_empty_reply_is_not_a_handled_command():
    """The regression. Nothing spoken, nothing run — the mic must not re-arm."""
    handled, spoken_aloud = _drive(_response(spoken=""))

    assert not spoken_aloud, f"an empty reply somehow spoke: {spoken_aloud!r}"
    assert handled is False, (
        "a turn with no spoken text and no tool calls reported success, so "
        "wake_word._start_turn reopens the follow-up window for another 8s "
        "instead of counting an empty capture"
    )


def test_whitespace_only_is_also_empty():
    """`spoken_text` arrives from a model; blank is as likely as empty."""
    handled, _ = _drive(_response(spoken="   \n  "))
    assert handled is False


def test_a_silent_tool_call_still_counts_as_handled():
    """The half that makes the change safe. A tool that ran is work the user
    asked for, whether or not the planner narrated it — treating that as an
    empty capture would close the chain after real actions."""
    call = ToolCall(name="volume_up", args={}, result=ToolResult.success(""),
                    latency_ms=5, status="success")
    handled, _ = _drive(_response(spoken="", tool_calls=[call]))
    assert handled is True, (
        "a turn that actually ran a tool was counted as producing nothing"
    )


def test_a_streamed_turn_with_a_blank_final_counts_as_handled():
    """Sentences already went to the speaker. `reply` and `sq.spoke_anything`
    are alternatives at the fallback check, so reading only `reply` here would
    call a turn the user HEARD an empty capture."""
    handled, spoken_aloud = _drive(_response(spoken=""),
                                   stream_sentences=("Here you go.",))
    assert spoken_aloud == ["Here you go."], spoken_aloud
    assert handled is True, (
        "the turn streamed a sentence to TTS and was still reported as "
        "producing nothing"
    )


def test_a_normal_reply_still_reports_success():
    """Guard against fixing this by making every turn look empty."""
    handled, _ = _drive(_response(spoken="Thirteen windows are open."))
    assert handled is True


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
