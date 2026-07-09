"""Phase 4B — first-sentence TTS streaming.

Three axes:
  * Brain._is_sentence_complete — the boundary detector.
  * SentenceQueue — the interruptible per-sentence drain.
  * _run_brain_streaming — the trigger integration: chunks from
    brain.run_stream flow into the queue, sentence 1 dispatched before
    sentence N is produced, interrupt cancels pending, single-sentence
    fallback still speaks.

speak_stream is patched with a fake that just records the text — no
Piper, no audio hardware.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Sentence-boundary detector ─────────────────────────────────────────

def test_is_sentence_complete_basic_boundaries():
    from backend.core.brain import Brain
    b = Brain()
    # All above the 10-char minimum length guard
    assert b._is_sentence_complete("Hello world.") is True
    assert b._is_sentence_complete("How are you?") is True
    assert b._is_sentence_complete("Watch out for that!") is True
    print("  [PASS] period / question / exclamation counted as boundaries")


def test_is_sentence_complete_min_length_guard():
    """Very short punctuated fragments ('Hi.', 'Ok.') should not fire — the
    real intent is to avoid dispatching a 3-word 'sentence' as its own TTS
    call. Uses len>10 in the current impl."""
    from backend.core.brain import Brain
    b = Brain()
    assert b._is_sentence_complete("Hi.") is False  # too short
    assert b._is_sentence_complete("This is long enough.") is True
    print("  [PASS] short punctuated fragments not treated as boundaries")


def test_is_sentence_complete_no_boundary():
    from backend.core.brain import Brain
    b = Brain()
    assert b._is_sentence_complete("Still going with no punctuation yet") is False
    assert b._is_sentence_complete("") is False
    print("  [PASS] no boundary → False")


# ── SentenceQueue ─────────────────────────────────────────────────────

def _install_fake_tts(spoken_log: list, delay: float = 0.0):
    """Patch speak_stream so it just records the sentence text.

    Returns the patcher (for cleanup)."""
    async def fake_speak_stream(text):
        spoken_log.append(text)
        yield {"status": "started", "text": text}
        if delay:
            await asyncio.sleep(delay)
        yield {"status": "finished", "text": text}

    return patch("backend.ai_modules.speech.tts_queue.speak_stream", side_effect=fake_speak_stream)


def _install_fake_stop(stop_log: list):
    def fake_stop():
        stop_log.append(True)
    return patch("backend.ai_modules.speech.tts_queue.stop_speech", side_effect=fake_stop)


def test_sentence_queue_speaks_in_order():
    """Multiple sentences enqueued → speak_stream called in the same order."""
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]):
            q = SentenceQueue()
            await q.start()
            await q.enqueue("First sentence.")
            await q.enqueue("Second sentence.")
            await q.enqueue("Third sentence.")
            await q.finish()
        return spoken

    spoken = asyncio.run(run())
    assert spoken == ["First sentence.", "Second sentence.", "Third sentence."], spoken
    print("  [PASS] sentences spoken in enqueue order")


def test_sentence_queue_interrupt_drains_pending_and_stops_current():
    """Interrupt mid-drain: stop_speech called AND remaining sentences dropped."""
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def run():
        spoken = []
        stop_calls = []
        # Add a delay so we can interrupt mid-playback
        with _install_fake_tts(spoken, delay=0.2), _install_fake_stop(stop_calls):
            q = SentenceQueue()
            await q.start()
            await q.enqueue("Sentence one that takes a moment.")
            await q.enqueue("Sentence two should be cancelled.")
            await q.enqueue("Sentence three should also be cancelled.")
            # Let sentence 1 start playing
            await asyncio.sleep(0.05)
            q.interrupt()
            # Give consumer a chance to bail
            try:
                await asyncio.wait_for(q._task, timeout=1.0)
            except asyncio.TimeoutError:
                pass
        return spoken, stop_calls

    spoken, stop_calls = asyncio.run(run())
    assert len(stop_calls) >= 1, "stop_speech must be called by interrupt()"
    assert spoken == ["Sentence one that takes a moment."], (
        f"only sentence 1 should have started before interrupt; got {spoken}"
    )
    print("  [PASS] interrupt() halts current sentence AND drops pending queue")


def test_sentence_queue_enqueue_no_op_after_interrupt():
    """Late-arriving chunks from brain.run_stream (arriving after user
    barge-in) must not sneak past the interrupt and get spoken."""
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]):
            q = SentenceQueue()
            await q.start()
            q.interrupt()
            await q.enqueue("Should never be spoken.")
            await asyncio.sleep(0.05)
            # No finish call needed — interrupt already sentinel'd
            try:
                await asyncio.wait_for(q._task, timeout=1.0)
            except asyncio.TimeoutError:
                pass
        return spoken

    spoken = asyncio.run(run())
    assert spoken == [], f"expected empty, got {spoken}"
    print("  [PASS] enqueue after interrupt is a no-op")


def test_sentence_queue_empty_string_skipped():
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]):
            q = SentenceQueue()
            await q.start()
            await q.enqueue("")
            await q.enqueue("   ")
            await q.enqueue("Real sentence.")
            await q.finish()
        return spoken, q.spoke_anything

    spoken, anything = asyncio.run(run())
    assert spoken == ["Real sentence."], spoken
    assert anything is True
    print("  [PASS] empty/whitespace-only sentences skipped, spoke_anything reflects real ones")


def test_sentence_queue_spoke_anything_false_when_nothing_enqueued():
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def run():
        with _install_fake_tts([]), _install_fake_stop([]):
            q = SentenceQueue()
            await q.start()
            await q.finish()
            return q.spoke_anything

    assert asyncio.run(run()) is False
    print("  [PASS] spoke_anything=False when no sentences enqueued")


# ── _run_brain_streaming: trigger integration ─────────────────────────

def _canned_brain_stream(chunks):
    """Return an async-generator factory that yields the given BrainChunks."""
    from backend.core.brain import BrainChunk

    async def _stream(_request):
        for c in chunks:
            yield c
    return _stream


def _canned_response(text: str = "final answer"):
    from backend.core.brain import BrainResponse
    return BrainResponse(spoken_text=text, intent={}, tool_calls=[], execution_trace=[], latency_ms=0)


def test_run_brain_streaming_multi_sentence_order():
    """tts_ready chunks arrive interleaved with token chunks — the queue
    should drain them in yield order."""
    from backend.core.brain import BrainChunk
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="token", content="First"),
        BrainChunk(type="token", content=" sentence."),
        BrainChunk(type="tts_ready", content="First sentence."),
        BrainChunk(type="token", content=" Second"),
        BrainChunk(type="token", content=" one here."),
        BrainChunk(type="tts_ready", content="Second one here."),
        BrainChunk(type="final", content=_canned_response("First sentence. Second one here.")),
    ]

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            resp = await _run_brain_streaming(object())
        return spoken, resp

    spoken, resp = asyncio.run(run())
    assert spoken == ["First sentence.", "Second one here."], spoken
    assert resp.spoken_text == "First sentence. Second one here."
    print("  [PASS] streaming: sentences dispatched in stream order")


def test_run_brain_streaming_no_tts_ready_returns_final_only():
    """Response with no sentence boundary → no tts_ready chunks emitted.
    _run_brain_streaming returns the final response with spoke_anything=False;
    the CALLER (in trigger) speaks it via the fallback path."""
    from backend.core.brain import BrainChunk
    from backend.ai_modules.speech.tts_queue import get_sentence_queue
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="token", content="Short answer"),
        BrainChunk(type="final", content=_canned_response("Short answer")),
    ]

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            resp = await _run_brain_streaming(object())
        return spoken, resp, get_sentence_queue().spoke_anything

    spoken, resp, anything = asyncio.run(run())
    assert spoken == [], f"no sentence boundary should have streamed nothing, got {spoken}"
    assert anything is False, "spoke_anything must be False so caller does fallback"
    assert resp.spoken_text == "Short answer"
    print("  [PASS] no-boundary response: nothing streamed, caller falls back to full-response speak")


def test_run_brain_streaming_tool_call_turn_no_speech():
    """Tool-call turn produces empty spoken_text — nothing should be spoken."""
    from backend.core.brain import BrainChunk
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="tool_start", content={"name": "open_url"}),
        BrainChunk(type="tool_end", content={"name": "open_url", "result": "ok"}),
        BrainChunk(type="final", content=_canned_response("")),  # empty spoken text
    ]

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            resp = await _run_brain_streaming(object())
        return spoken, resp

    spoken, resp = asyncio.run(run())
    assert spoken == [], f"tool-call turn should not speak, got {spoken}"
    assert resp.spoken_text == ""
    print("  [PASS] tool-call turn with empty spoken_text: no speech, no crash")


def test_run_brain_streaming_no_final_chunk_still_returns_response():
    """If the stream ends without a `final` chunk (LLM crash mid-stream),
    we still return a BrainResponse so downstream code doesn't NPE."""
    from backend.core.brain import BrainChunk
    from backend.daemon.trigger import _run_brain_streaming

    chunks = [
        BrainChunk(type="context_ready"),
        BrainChunk(type="token", content="Partial"),
        # No `final` chunk
    ]

    async def run():
        spoken = []
        with _install_fake_tts(spoken), _install_fake_stop([]), \
             patch("backend.daemon.trigger.brain.run_stream", side_effect=_canned_brain_stream(chunks)), \
             patch("backend.daemon.trigger.state_manager"):
            resp = await _run_brain_streaming(object())
        return resp

    resp = asyncio.run(run())
    assert resp is not None
    assert resp.spoken_text == ""  # graceful default
    print("  [PASS] missing final chunk → empty BrainResponse (no crash)")


if __name__ == "__main__":
    test_is_sentence_complete_basic_boundaries()
    test_is_sentence_complete_min_length_guard()
    test_is_sentence_complete_no_boundary()
    test_sentence_queue_speaks_in_order()
    test_sentence_queue_interrupt_drains_pending_and_stops_current()
    test_sentence_queue_enqueue_no_op_after_interrupt()
    test_sentence_queue_empty_string_skipped()
    test_sentence_queue_spoke_anything_false_when_nothing_enqueued()
    test_run_brain_streaming_multi_sentence_order()
    test_run_brain_streaming_no_tts_ready_returns_final_only()
    test_run_brain_streaming_tool_call_turn_no_speech()
    test_run_brain_streaming_no_final_chunk_still_returns_response()
    print("All Phase 4B streaming tests passed.")
