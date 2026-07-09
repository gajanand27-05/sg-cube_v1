"""Phase 4B — sentence queue for streaming TTS.

Brain.run_stream() yields a `tts_ready` chunk per completed sentence.
This queue drains them one-at-a-time through speak_stream(), so:
  * Time-to-first-audio drops (start speaking sentence 1 before the LLM
    finishes the full response).
  * Ordering is preserved (sentence N is not spoken until N-1 finishes).
  * Barge-in halts current playback via stop_speech() AND drains any
    pending sentences via interrupt() — otherwise queued sentences would
    resume speaking after the user cut in.

Piper's stop_speech / _stop_event lives at module scope in tts_piper.py,
so overlapping speak_stream() calls would race. We serialize by putting
one consumer task in front of the queue.
"""
import asyncio
import logging
from typing import Optional

from backend.ai_modules.speech.tts_piper import speak_stream, stop_speech

log = logging.getLogger(__name__)


class SentenceQueue:
    """Serialize per-sentence TTS with an interruptible drain loop.

    Lifecycle per turn:
      1. `start()` — clear state, spawn the consumer task.
      2. `enqueue(sentence)` — as sentences arrive from brain.run_stream.
      3. `finish()` — signal end of turn; await all sentences drained.
    Between (1) and (3), `interrupt()` can be called from any task to
    cancel current + pending playback.
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._interrupted: bool = False
        self._spoke_anything: bool = False

    @property
    def spoke_anything(self) -> bool:
        """Did any sentence get past enqueue? Used by trigger to decide
        whether to fall back to speaking a full response after the stream."""
        return self._spoke_anything

    async def start(self) -> None:
        self._interrupted = False
        self._spoke_anything = False
        # Fresh queue — drain any leftovers from a prior turn defensively.
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._task = asyncio.create_task(self._consumer())

    async def enqueue(self, sentence: str) -> None:
        """Add a sentence. No-op after interrupt() so late-arriving chunks
        from brain.run_stream don't outlive the barge-in."""
        if self._interrupted:
            return
        if not sentence or not sentence.strip():
            return
        self._spoke_anything = True
        await self._queue.put(sentence)

    async def finish(self) -> None:
        """End-of-turn: send sentinel, await consumer to drain and exit."""
        await self._queue.put(None)  # sentinel
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def interrupt(self) -> None:
        """Stop current playback and cancel every queued sentence.

        Safe to call from any task. Idempotent.
        """
        if self._interrupted:
            return
        self._interrupted = True
        # Kill Piper's current playback synchronously.
        try:
            stop_speech()
        except Exception as e:
            log.warning(f"stop_speech raised during interrupt: {e}")
        # Drain remaining sentences.
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # Poke the consumer with a sentinel so it exits even if it's
        # currently blocked on queue.get().
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def _consumer(self) -> None:
        """Drain the queue, playing each sentence through speak_stream."""
        while True:
            sentence = await self._queue.get()
            if sentence is None:
                return
            if self._interrupted:
                return
            try:
                async for _ in speak_stream(sentence):
                    if self._interrupted:
                        return
            except Exception as e:
                log.warning(f"TTS sentence failed: {e}")
                # Continue draining; a single bad sentence shouldn't kill
                # the whole turn's playback.


# Module-level singleton — one voice turn at a time.
_QUEUE: Optional[SentenceQueue] = None


def get_sentence_queue() -> SentenceQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = SentenceQueue()
    return _QUEUE
