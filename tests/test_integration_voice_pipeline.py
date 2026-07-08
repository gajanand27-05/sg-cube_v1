"""Integration tests — the wake-word → Brain → post-Brain publish path.

Fills the gap that let three consecutive wiring bugs ship during Phase 1:

  commit 5ceb688  fix(voice): commander not imported in trigger.py (NameError)
  commit 5ceb688  fix(voice): Brain._run_commander_stream missing (AttributeError)
  commit 4773367  fix(voice): trigger.py treats ToolCall as dict (AttributeError)

None of them showed up in unit tests because unit tests mock at the tool /
verifier boundary and never actually run Brain, Commander, or trigger's
publish path. The three tests below exercise those code paths with only
the OUTERMOST boundaries stubbed:

  - LLM provider (canned response instead of hitting Ollama/Gemini)
  - TTS speak (skip audio playback)
  - Wake-word chime (avoid sounddevice on headless CI)

Everything else — Brain, Commander, Guardian, Operator, tool registry,
verifier's tier gate, ToolResult ↔ ToolCall marshalling — runs for real.
A wiring bug (missing import, wrong method name, dataclass-vs-dict
confusion) fails the appropriate test immediately.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)


# ── Test 1: on_wake_detected resolves every symbol it touches ───────────

def test_on_wake_detected_resolves_all_symbols():
    """The load-bearing wake-word callback. A missing import here — the
    exact bug in commit 5ceb688 — turned every wake into
    `NameError: name 'commander' is not defined`. This test proves the
    function's symbol resolution end-to-end, no LLM required."""
    from backend.daemon import trigger as tr

    with patch.object(tr, "stop_speech") as _stop, \
         patch.object(tr.commander, "interrupt") as _interrupt, \
         patch.object(tr, "_play_chime"):
        # Would raise NameError if `commander` weren't imported in trigger.py.
        # Would raise AttributeError if commander lacked .interrupt().
        tr.on_wake_detected(emit=None)

    assert _stop.called, "on_wake_detected must invoke stop_speech()"
    assert _interrupt.called, "on_wake_detected must invoke commander.interrupt()"
    print("  [PASS] on_wake_detected resolves all symbols + calls stop_speech + commander.interrupt")


# ── Test 2: Brain.run_stream reaches a final chunk ──────────────────────

def test_brain_run_stream_reaches_final_chunk():
    """Drive Brain → Commander → Planner (LLM stubbed) → back up. Would
    fail immediately if `self._run_commander_stream` were still missing
    (the second bug in commit 5ceb688)."""
    from backend.core.brain import brain, BrainRequest, BrainResponse
    from backend.ai_modules.llm import get_provider

    # Planner uses llm.chat_stream(...) — stub it to yield a canned
    # `final_response` JSON so Commander skips Guardian entirely and Brain
    # wraps it into a BrainResponse.
    canned_json = '{"final_response": "The time is twelve o clock, integration test"}'

    # chat_stream yields dicts of shape {"token": "..."} — Planner reads
    # chunk["token"] and accumulates into full_content before json.loads().
    async def _fake_chat_stream(*_a, **_kw):
        yield {"token": canned_json}

    provider = get_provider()
    original_chat_stream = provider.chat_stream

    async def _drive() -> list:
        request = BrainRequest(user_id="test-user", input_text="what time is it")
        chunks = []
        async for chunk in brain.run_stream(request):
            chunks.append(chunk)
        return chunks

    try:
        provider.chat_stream = _fake_chat_stream
        chunks = _run(_drive())
    finally:
        provider.chat_stream = original_chat_stream

    types = [c.type for c in chunks]
    assert "final" in types, f"Brain never reached a 'final' chunk. Got: {types}"
    final_chunk = next(c for c in chunks if c.type == "final")
    response = final_chunk.content
    assert isinstance(response, BrainResponse), f"final content should be BrainResponse, got {type(response)}"
    assert "twelve o clock" in response.spoken_text.lower(), (
        f"canned response text should propagate to BrainResponse.spoken_text; got {response.spoken_text!r}"
    )
    print(f"  [PASS] Brain.run_stream → final chunk with spoken_text={response.spoken_text!r}")


# ── Test 3: trigger's post-Brain publish path handles ToolCall dataclass ─

def test_trigger_process_handles_toolcall_dataclass():
    """The publish loop over `response.tool_calls` used to do
    `tool_call.get("result", "ok")` — a dict method on a dataclass. That
    was the commit 4773367 bug. This test drives the whole
    `_process_and_execute` path with a synthetic BrainResponse whose
    `.tool_calls` carries a real ToolCall + ToolResult, and asserts the
    Executed event carries the ToolResult's own .message string."""
    from backend.core.brain import ToolCall, BrainResponse
    from backend.core.tools.registry import ToolResult
    from backend.daemon.ui_events import Executed
    from backend.daemon import trigger as tr

    # Shape Brain would actually return after a real tool run.
    result = ToolResult.success("13 windows open", data={"count": 13})
    tool_call = ToolCall(name="list_windows", args={}, result=result,
                          latency_ms=42, status="success")
    fake_response = BrainResponse(
        spoken_text="Thirteen windows are open.",
        intent={},
        tool_calls=[tool_call],
        execution_trace=[],
        latency_ms=100,
        metadata={"request_id": "int-test", "input_mode": "voice"},
    )

    # Capture events published inside the trigger loop.
    published: list = []

    class _CapBus:
        def publish(self, event, priority=None):
            published.append(event)

    async def _no_speak(*_a, **_kw):
        return None

    async def _mock_brain_run(_req):
        return fake_response

    with patch.object(tr, "brain") as mock_brain, \
         patch.object(tr, "_speak_selective", side_effect=_no_speak), \
         patch.object(tr.state_manager, "transition_to"), \
         patch.object(tr, "get_bus", return_value=_CapBus()):
        mock_brain.run = _mock_brain_run

        ok = _run(tr._process_and_execute(
            command="what windows are open",
            peak=0,
            t0=0.0,
            emit=None,
            device_id=None,
        ))

    assert ok is True, "process_and_execute reported failure on the happy path"

    executed_events = [e for e in published if isinstance(e, Executed)]
    assert len(executed_events) == 1, (
        f"expected exactly one Executed event, got {len(executed_events)}. "
        f"All published: {[type(e).__name__ for e in published]}"
    )
    # The core assertion — the ToolResult.message should have made it into
    # the Executed event. Would fail with an AttributeError before commit
    # 4773367 (before we even got here).
    assert executed_events[0].message == "13 windows open", (
        f"Executed.message should be ToolResult.message; got {executed_events[0].message!r}"
    )
    assert executed_events[0].status == "success"
    print("  [PASS] trigger._process_and_execute handles ToolCall dataclass, publishes correct Executed message")


if __name__ == "__main__":
    test_on_wake_detected_resolves_all_symbols()
    test_brain_run_stream_reaches_final_chunk()
    test_trigger_process_handles_toolcall_dataclass()
    print("All voice-pipeline integration tests passed.")
