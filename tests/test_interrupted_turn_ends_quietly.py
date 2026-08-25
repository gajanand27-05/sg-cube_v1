"""T-turn-pile-up: what an interrupted turn does after it is interrupted.

Two defects, both of which keep a superseded turn alive and talking.

1. Brain ignores the commander's interrupt chunk. `run_stream` has branches
   for token/prose/tool_start/tool_end/final_response and nothing else, so an
   interrupted turn falls out of the `async for` and builds a response from
   `summarize_outcome([])` — which is the string

       "I'm not sure what to do with that — could you say it again?"

   That is the single most repeated line in both dogfooding logs. The user
   cut the assistant off and was answered with a comprehension failure, which
   is indistinguishable from actually being misheard.

2. SentenceQueue.interrupt() mutates its asyncio.Queue from the WAKE-WORD
   LISTENER THREAD (via on_wake_detected). put_nowait wakes a pending getter
   by completing a future that belongs to another loop, and the wakeup is
   posted with call_soon, not call_soon_threadsafe — so the owning loop is
   never poked and may sit in select() until something unrelated wakes it.
   The interrupt does not land, the old turn keeps speaking, and the new turn
   spends the full _TURN_HANDOVER_TIMEOUT_S waiting for it:

       [wake] previous turn still running after 15s; starting anyway
"""
import asyncio
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.brain import Brain, BrainRequest, _NOTHING_HAPPENED
from backend.core.agents.commander import CommanderChunk


# ── 1. an interrupted turn must not speak the confused fallback ────────

def test_interrupted_turn_does_not_speak_the_confused_fallback():
    brain = Brain()

    class _InterruptedCommander:
        async def run_stream(self, text, context, user_id=None):
            yield CommanderChunk("token", '{"final_res')
            yield CommanderChunk("interrupted", "Interrupted")

    brain.commander = _InterruptedCommander()

    async def _drive():
        final = None
        async for chunk in brain.run_stream(
            BrainRequest(user_id="u", input_text="open whatsapp", input_mode="voice")
        ):
            if chunk.type == "final":
                final = chunk.content
        return final

    final = asyncio.run(asyncio.wait_for(_drive(), timeout=30))

    assert final is not None, "interrupted turn never produced a final chunk"
    assert final.spoken_text != _NOTHING_HAPPENED, (
        "interrupting the assistant made it answer 'I'm not sure what to do "
        "with that' — the user was cut off, not misheard"
    )
    assert not final.spoken_text.strip(), (
        f"an interrupted turn should end silently, got {final.spoken_text!r}"
    )


def test_uninterrupted_turn_still_gets_the_honest_fallback():
    """The fallback is load-bearing everywhere else — do not blunt it."""
    brain = Brain()

    class _EmptyCommander:
        async def run_stream(self, text, context, user_id=None):
            return
            yield  # pragma: no cover - makes this an async generator

    brain.commander = _EmptyCommander()

    async def _drive():
        async for chunk in brain.run_stream(
            BrainRequest(user_id="u", input_text="do a thing", input_mode="voice")
        ):
            if chunk.type == "final":
                return chunk.content

    final = asyncio.run(asyncio.wait_for(_drive(), timeout=30))
    assert final.spoken_text == _NOTHING_HAPPENED


# ── 2. interrupt() must land when called from another thread ───────────

def test_sentence_queue_interrupt_wakes_the_owning_loop():
    """The listener thread interrupts; the turn's loop must actually wake.

    The consumer is parked on `await self._queue.get()`. interrupt() pokes it
    with put_nowait(None), which completes the getter's future and posts the
    wakeup with call_soon — and call_soon, unlike call_soon_threadsafe, does
    not write to the loop's self-pipe. A loop asleep in select() therefore
    does not learn about it until some unrelated timer fires. Measured here by
    parking the loop on a 3s timer and seeing whether the consumer exits
    before it.
    """
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    async def _drive():
        q = SentenceQueue()
        await q.start()
        await asyncio.sleep(0.05)  # consumer is now parked on queue.get()

        # Exactly how on_wake_detected does it: another thread entirely — and
        # crucially, while this loop is ASLEEP. Interrupting from a thread the
        # loop is currently blocked join()ing hides the bug, because the loop
        # drains its callback queue the moment it resumes for its own reasons.
        def _late_interrupt():
            time.sleep(0.2)
            q.interrupt()

        threading.Thread(target=_late_interrupt, daemon=True).start()

        t0 = time.monotonic()
        try:
            await asyncio.wait_for(asyncio.shield(q._task), timeout=3)
        except asyncio.TimeoutError:
            pass
        return time.monotonic() - t0, q._task.done()

    with patch("backend.ai_modules.speech.tts_queue.stop_speech"):
        elapsed, done = asyncio.run(asyncio.wait_for(_drive(), timeout=20))

    assert done, "the consumer never noticed the interrupt at all"
    assert elapsed < 1.0, (
        f"interrupt from another thread took {elapsed:.1f}s to wake the loop; "
        "that latency is what makes the next turn wait out the 15s handover"
    )


def test_sentence_queue_interrupt_still_drains_pending_sentences():
    """Whatever the wakeup mechanism, queued sentences must not survive."""
    from backend.ai_modules.speech.tts_queue import SentenceQueue

    spoken: list[str] = []

    async def fake_speak_stream(text):
        spoken.append(text)
        yield {"status": "started", "text": text}
        yield {"status": "finished", "text": text}

    async def _drive():
        q = SentenceQueue()
        await q.start()
        await q.enqueue("First sentence, already being spoken.")
        await q.enqueue("Second sentence nobody should ever hear.")
        await q.enqueue("Third sentence nobody should ever hear.")

        t = threading.Thread(target=q.interrupt)
        t.start()
        t.join()
        await asyncio.wait_for(q.finish(), timeout=5)

    with patch("backend.ai_modules.speech.tts_queue.speak_stream",
               side_effect=fake_speak_stream), \
         patch("backend.ai_modules.speech.tts_queue.stop_speech"):
        asyncio.run(asyncio.wait_for(_drive(), timeout=20))

    assert len(spoken) <= 1, f"queued sentences survived the interrupt: {spoken!r}"
