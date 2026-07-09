"""Phase 4C — round-trip latency instrumentation.

Three axes:
  * TurnLatency: mark / seal / to_dict, and idempotence guards.
  * LatencyLedger: recording, recent(), ring buffer capacity.
  * Integration: a full drive of _run_brain_streaming against canned
    BrainChunks records all expected stages.
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── TurnLatency unit tests ──────────────────────────────────────────────

def test_mark_records_stage():
    from backend.core.latency import TurnLatency
    t = TurnLatency(request_id="abc")
    t.mark("wake")
    time.sleep(0.02)
    t.mark("stt_done")
    assert "wake" in t.stages
    assert "stt_done" in t.stages
    assert t.stages["stt_done"] >= t.stages["wake"]
    print("  [PASS] mark records elapsed ms per stage in order")


def test_mark_is_idempotent_first_wins():
    """`planner_first_token` gets marked on every token chunk — first must win
    so we don't overwrite with the LAST token's time."""
    from backend.core.latency import TurnLatency
    t = TurnLatency(request_id="abc")
    t.mark("planner_first_token")
    first = t.stages["planner_first_token"]
    time.sleep(0.02)
    t.mark("planner_first_token")
    assert t.stages["planner_first_token"] == first, "repeated mark must NOT overwrite"
    print("  [PASS] mark idempotent — first call wins")


def test_seal_stamps_total_and_freezes():
    from backend.core.latency import TurnLatency
    t = TurnLatency(request_id="abc")
    t.mark("wake")
    t.seal()
    assert "total" in t.stages
    total = t.stages["total"]
    # Post-seal marks are ignored
    time.sleep(0.02)
    t.mark("stt_done")
    assert "stt_done" not in t.stages
    assert t.stages["total"] == total
    print("  [PASS] seal stamps total AND freezes further marks")


def test_to_dict_shape():
    from backend.core.latency import TurnLatency
    t = TurnLatency(request_id="abc", mode="voice")
    t.mark("wake")
    t.mark("stt_done")
    d = t.to_dict()
    assert d["request_id"] == "abc"
    assert d["mode"] == "voice"
    assert set(d["stages_ms"].keys()) == {"wake", "stt_done"}
    print("  [PASS] to_dict returns request_id + mode + stages_ms")


# ── LatencyLedger ──────────────────────────────────────────────────────

def test_ledger_record_and_recent():
    from backend.core.latency import TurnLatency, LatencyLedger
    l = LatencyLedger(capacity=5)
    for i in range(3):
        t = TurnLatency(request_id=f"t{i}")
        t.mark("wake")
        l.record(t)
    recent = l.recent(n=10)
    assert len(recent) == 3
    assert recent[0]["request_id"] == "t0"
    assert recent[-1]["request_id"] == "t2"
    # Records auto-seal so total is stamped
    assert "total" in recent[0]["stages_ms"]
    print("  [PASS] record + recent returns turns in insertion order, sealed")


def test_ledger_ring_buffer_capacity():
    from backend.core.latency import TurnLatency, LatencyLedger
    l = LatencyLedger(capacity=3)
    for i in range(5):
        l.record(TurnLatency(request_id=f"t{i}"))
    recent = l.recent(n=10)
    assert len(recent) == 3, f"capacity 3 should retain last 3, got {len(recent)}"
    assert [r["request_id"] for r in recent] == ["t2", "t3", "t4"]
    print("  [PASS] ring buffer drops oldest at capacity")


# ── Integration: streaming pipeline records real stages ────────────────

def _canned_brain_stream(chunks):
    async def _stream(_request):
        for c in chunks:
            yield c
    return _stream


def _canned_response(text="answer"):
    from backend.core.brain import BrainResponse
    return BrainResponse(spoken_text=text, intent={}, tool_calls=[], execution_trace=[], latency_ms=0)


def test_run_brain_streaming_records_all_stages():
    from backend.core.brain import BrainChunk
    from backend.core.latency import TurnLatency
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="token", content="First"),
        BrainChunk(type="token", content=" sentence."),
        BrainChunk(type="tool_start", content={"name": "get_stock"}),
        BrainChunk(type="tool_end", content={"name": "get_stock", "result": "ok"}),
        BrainChunk(type="tts_ready", content="First sentence."),
        BrainChunk(type="final", content=_canned_response("First sentence.")),
    ]

    async def _fake_speak_stream(text):
        yield {"status": "started", "text": text}
        yield {"status": "finished", "text": text}

    async def run():
        turn = TurnLatency(request_id="abc", mode="voice")
        turn.mark("wake")
        turn.mark("stt_done")
        turn.mark("orchestrator_route")
        with patch("backend.ai_modules.speech.tts_queue.speak_stream", side_effect=_fake_speak_stream), \
             patch("backend.ai_modules.speech.tts_queue.stop_speech"), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            await _run_brain_streaming(object(), turn=turn)
        return turn

    turn = asyncio.run(run())
    assert "wake" in turn.stages
    assert "stt_done" in turn.stages
    assert "orchestrator_route" in turn.stages
    assert "context_ready" in turn.stages, "context_ready chunk was in the stream"
    assert "planner_first_token" in turn.stages, "at least one token was streamed"
    assert "first_tool_start" in turn.stages
    assert "first_tool_end" in turn.stages
    assert "first_audio_out" in turn.stages, "tts_ready must record first_audio_out"
    print("  [PASS] streaming pipeline records every stage")


def test_run_brain_streaming_skips_missing_stages():
    """A tool-call-only turn with no spoken output has no tts_ready or tokens —
    those stages should be ABSENT from the record, not zero-filled."""
    from backend.core.brain import BrainChunk
    from backend.core.latency import TurnLatency
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="tool_start", content={"name": "close_chrome"}),
        BrainChunk(type="tool_end", content={"name": "close_chrome", "result": "ok"}),
        BrainChunk(type="final", content=_canned_response("")),
    ]

    async def _fake_speak_stream(text):
        yield {"status": "started", "text": text}

    async def run():
        turn = TurnLatency(request_id="abc", mode="voice")
        turn.mark("wake")
        with patch("backend.ai_modules.speech.tts_queue.speak_stream", side_effect=_fake_speak_stream), \
             patch("backend.ai_modules.speech.tts_queue.stop_speech"), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            await _run_brain_streaming(object(), turn=turn)
        return turn

    turn = asyncio.run(run())
    assert "wake" in turn.stages
    assert "context_ready" in turn.stages
    assert "first_tool_start" in turn.stages
    assert "planner_first_token" not in turn.stages, "no tokens streamed → no mark"
    assert "first_audio_out" not in turn.stages, "no tts_ready → no mark"
    print("  [PASS] missing stages omitted, not zero-filled")


if __name__ == "__main__":
    test_mark_records_stage()
    test_mark_is_idempotent_first_wins()
    test_seal_stamps_total_and_freezes()
    test_to_dict_shape()
    test_ledger_record_and_recent()
    test_ledger_ring_buffer_capacity()
    test_run_brain_streaming_records_all_stages()
    test_run_brain_streaming_skips_missing_stages()
    print("All Phase 4C latency tests passed.")
