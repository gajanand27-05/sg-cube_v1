"""T-interrupt-cancels-the-whole-turn.

`commander.interrupt()` recorded `asyncio.current_task()` — which on the voice
path is the main task of `asyncio.run(_handle_wake_async(...))`, not the
planner loop. Cancelling it therefore aborted whatever the TURN was doing,
including TTS playback, long after the planner was finished. Two live
sightings, one per dogfooding log:

    File "backend/daemon/trigger.py", line 449, in _process_and_execute
        await _speak_selective(reply, device_id)
      ...
      File "backend/ai_modules/speech/tts_piper.py", line 410, in speak_stream
        await session.player
    asyncio.exceptions.CancelledError

    [ai] response: I attempted to open the Onyx application, but the task was
                   cancelled, so it was not opened.

Nothing caught it — CancelledError is a BaseException, so the `except
Exception` guards in trigger and wake_word both miss it — and the wake-turn
thread died with the state machine stranded in SPEAKING.

Two properties are asserted here:
  1. interrupt() aborts only the commander's own work; the task consuming
     run_stream survives and runs its post-stream code (that code is TTS).
  2. interrupt() is safe to call from ANOTHER THREAD, which is where it is
     actually called from (the wake-word listener).
"""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.commander import INTERRUPTED, CommanderAgent, CommanderChunk


def _commander_stuck_in(started: threading.Event) -> CommanderAgent:
    """A commander whose planner loop parks forever, like a slow LLM call."""
    agent = CommanderAgent()

    async def _fake_loop(text, context, user_id):
        yield CommanderChunk("token", "thinking")
        started.set()
        await asyncio.sleep(3600)  # the planner call we need to be able to abort
        yield CommanderChunk("final_response", "never reached")

    agent._run_loop_stream = _fake_loop
    return agent


def test_interrupt_does_not_cancel_the_consuming_task():
    """The turn survives its own interrupt and reaches the code that speaks."""
    started = threading.Event()
    agent = _commander_stuck_in(started)
    reached_tts = False

    async def turn():
        nonlocal reached_tts
        chunks = []
        async for chunk in agent.run_stream("hello", _ctx(), None):
            chunks.append(chunk)
            if chunk.type == "token":
                # Interrupt from a foreign thread, exactly as the wake-word
                # listener does via on_wake_detected/on_barge_in.
                threading.Thread(target=agent.interrupt).start()
        # Everything past here stands in for _speak_selective(). Before the
        # fix this was unreachable: the CancelledError landed HERE.
        await asyncio.sleep(0)
        reached_tts = True
        return chunks

    chunks = asyncio.run(asyncio.wait_for(turn(), timeout=10))

    assert reached_tts, "interrupt cancelled the turn task, not just the planner"
    assert chunks[-1].type == INTERRUPTED and chunks[-1].content == "Interrupted"


def test_interrupt_from_another_thread_actually_lands():
    """Task.cancel() is not thread-safe; the abort must still take effect."""
    started = threading.Event()
    agent = _commander_stuck_in(started)

    async def turn():
        out = []
        async for chunk in agent.run_stream("hello", _ctx(), None):
            out.append(chunk)
            if chunk.type == "token":
                t = threading.Thread(target=agent.interrupt)
                t.start()
                t.join()
        return out

    # Without a thread-safe cancel this parks on the 3600s sleep and the
    # wait_for below is what ends the test.
    out = asyncio.run(asyncio.wait_for(turn(), timeout=10))
    assert [c.type for c in out] == ["token", INTERRUPTED]


def test_interrupt_after_stream_is_abandoned_is_a_no_op():
    """A consumer that breaks early must not leave a live turn cancellable.

    brain.run() returns out of `async for chunk in run_stream(...)` the moment
    it sees a final chunk, which leaves the generator suspended. If the
    commander is still pointing at the turn's task at that moment, the next
    wake word cancels a turn that has moved on to speaking — the reported bug.
    """
    agent = CommanderAgent()

    async def _fake_loop(text, context, user_id):
        yield CommanderChunk("final_response", "done")
        yield CommanderChunk("token", "trailing")

    agent._run_loop_stream = _fake_loop
    survived = False

    async def turn():
        nonlocal survived
        async for chunk in agent.run_stream("hello", _ctx(), None):
            if chunk.type == "final_response":
                break  # exactly what brain.run() does
        agent.interrupt()  # a new wake word arrives while we are speaking
        await asyncio.sleep(0)
        survived = True

    asyncio.run(asyncio.wait_for(turn(), timeout=10))
    assert survived, "a stale _current_task let interrupt cancel the speaking turn"


def _ctx():
    from backend.core.agent.context import ConversationContext

    return ConversationContext(session_id="test-interrupt")


@pytest.mark.parametrize("_run", range(3))
def test_interrupt_is_repeatable(_run):
    """Three runs — one clean pass is not evidence (see the ledger note)."""
    test_interrupt_does_not_cancel_the_consuming_task()
