"""TokenStreamEvent must carry displayable text, not the raw envelope.

The HUD's Onyx lane rendered `{"final_response": "The capital of France is
Paris."}` verbatim. It was reading `full_content`, which is the accumulated
RAW planner stream — a JSON envelope. This is the same defect as
T-tts-speaks-planner-json, one consumer over: that fix routed prose to TTS and
left the UI on the raw accumulation. The panel's own comment claimed
full_content was the safe field to render, which is how it survived review.

These drive the real PlannerAgent and read what it actually PUBLISHES. A test
asserting the dataclass has a `prose` field would pass while the publisher
still sent the envelope — this codebase has shipped that mistake before.
"""
import json
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.context.types import AgentContext
from backend.daemon.ui_events import TokenStreamEvent


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, event, priority=None):
        self.events.append(event)

    def token_streams(self):
        return [e for e in self.events if isinstance(e, TokenStreamEvent)]


def _chunks(text: str, size: int = 7):
    """Realistic tokenisation — the extractor is a character state machine and
    must survive the envelope being split anywhere."""
    return [text[i:i + size] for i in range(0, len(text), size)]


async def _run_planner(envelope: str, bus, request_id="req-1"):
    from backend.core.agents import planner as planner_mod
    from backend.core.agents.planner import PlannerAgent

    class _LLM:
        async def chat_stream(self, messages, task=None, temperature=None):
            for piece in _chunks(envelope):
                yield {"token": piece}

    agent = PlannerAgent()
    ctx = AgentContext(user_intent="what is the capital of France")
    ctx.request_id = request_id

    import unittest.mock as mock
    with mock.patch.object(planner_mod, "get_provider", lambda: _LLM()), \
         mock.patch.object(planner_mod, "get_bus", lambda: bus):
        async for _ in agent.generate_plan_stream("what is the capital of France", [], ctx):
            pass


@pytest.mark.asyncio
async def test_published_prose_is_clean_text_not_the_envelope():
    bus = _Bus()
    envelope = json.dumps({"final_response": "The capital of France is Paris."})
    await _run_planner(envelope, bus)

    streams = bus.token_streams()
    assert streams, "planner published no TokenStreamEvent at all"
    final_prose = streams[-1].prose
    assert final_prose == "The capital of France is Paris.", final_prose
    # The exact characters that appeared on the HUD.
    for ev in streams:
        assert "{" not in ev.prose and "final_response" not in ev.prose, ev.prose


@pytest.mark.asyncio
async def test_full_content_is_still_the_raw_stream():
    """Not a regression — other consumers (latency marks, the architecture
    overlay) depend on the raw accumulation. The fix adds a field, it does not
    repurpose one."""
    bus = _Bus()
    envelope = json.dumps({"final_response": "Paris."})
    await _run_planner(envelope, bus)
    assert bus.token_streams()[-1].full_content == envelope


@pytest.mark.asyncio
async def test_request_id_rides_along_for_turn_pairing():
    """The UI pairs a question with its own answer using this. Without it the
    transcript shows whatever answer arrived most recently."""
    bus = _Bus()
    await _run_planner(json.dumps({"final_response": "Paris."}), bus, request_id="abc123")
    assert all(e.request_id == "abc123" for e in bus.token_streams())


@pytest.mark.asyncio
async def test_prose_accumulates_rather_than_flickering():
    """The lane renders the payload directly, so each event must carry the
    whole prose so far. Per-token deltas would render one fragment at a time."""
    bus = _Bus()
    await _run_planner(json.dumps({"final_response": "One two three four."}), bus)
    proses = [e.prose for e in bus.token_streams() if e.prose]
    assert proses == sorted(proses, key=len), "prose is not monotonically growing"
    assert proses[-1] == "One two three four."


@pytest.mark.asyncio
async def test_tool_call_turn_publishes_no_prose():
    """Correct, not a gap: a tool_calls envelope has nothing speakable yet —
    those turns talk after execution. The lane stays empty instead of showing
    machinery."""
    bus = _Bus()
    envelope = json.dumps({"tool_calls": [{"name": "play_youtube", "args": {"query": "lofi"}}]})
    await _run_planner(envelope, bus)
    assert all(e.prose == "" for e in bus.token_streams())


if __name__ == "__main__":
    import asyncio
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            asyncio.run(fn())
            print(f"  [PASS] {name}")
