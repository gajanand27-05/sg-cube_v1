"""Phase 4B — sentence queue for streaming TTS.

Brain.run_stream() yields a `tts_ready` chunk per completed sentence.
This queue drains them one-at-a-time through speak_stream(), so:
  * Time-to-first-audio drops (start speaking sentence 1 before the LLM
    finishes the full response).
  * Ordering is preserved (sentence N is not spoken until N-1 finishes).
  * Barge-in halts current playback via stop_speech() AND drains any
    pending sentences via interrupt() — otherwise queued sentences would
    resume speaking after the user cut in.

This queue serializes sentences *within* a turn — one consumer task in front of
the queue, so sentence N never starts before N-1 finishes.

It does NOT protect against overlap *across* turns, and the note that used to
be here implied it did: it said Piper's module-scope stop_speech/_stop_event
meant "overlapping speak_stream() calls would race", as though this class were
the answer. It isn't. An HTTP /voice/say or the proactive handler can call
speak_stream on another loop entirely, which no amount of serializing here
prevents. That is fixed where it belongs — playback state is now per-call in
tts_piper.py, see _PlaybackSession and T-tts-loop-globals.
"""
import asyncio
import logging
import threading
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
    def depth(self) -> int:
        """Sentences still waiting to be spoken.

        Read-only and safe from any thread or loop: asyncio.Queue.qsize() is a
        deque length, so it never touches the loop this queue is bound to —
        the hazard T-tts-loop-globals documents. It transiently counts the
        end-of-turn sentinel, so 1 can mean "about to drain".
        """
        return self._queue.qsize()

    @property
    def spoke_anything(self) -> bool:
        """Did any sentence get past enqueue? Used by trigger to decide
        whether to fall back to speaking a full response after the stream."""
        return self._spoke_anything

    async def start(self) -> None:
        self._interrupted = False
        self._spoke_anything = False
        # Rebuild the queue rather than drain it. This is a module-level
        # singleton but handle_wake() runs asyncio.run() per capture, so the
        # queue built on turn N's loop is bound to a loop that is closed by
        # turn N+1 — "<Queue ...> is bound to a different event loop", which is
        # how Brain failed mid-turn. Constructing it here binds it to the loop
        # that will actually consume it. See T-tts-loop-globals.
        self._queue = asyncio.Queue()
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


# ── Queue ownership (same hazard as T-tts-loop-globals) ────────────────
#
# This used to be a module-level singleton reused by every turn, and `start()`
# rebinds `_queue` and `_task` to the CALLING loop. handle_wake() runs
# asyncio.run() per capture, so when two turn bodies overlap, turn N+1's
# start() replaced the task turn N was still awaiting in finish():
#
#     got Future <Task ... SentenceQueue._consumer()> attached to a
#     different loop            -> "Sorry, I encountered an error"
#     await wasn't used with future
#
# Turn serialization (wake_word._start_turn) made that rare but cannot make it
# unreachable: the handover join is bounded by _TURN_HANDOVER_TIMEOUT_S so a
# wedged turn cannot deafen the listener forever, and past that bound two turns
# run anyway. So each turn now OWNS its queue, and the module only remembers
# which one is current — for stop / wake / barge-in, which interrupt from the
# listener thread and must land on the turn that is actually speaking.
#
# Note the failure needs the foreign task to still be PENDING; awaiting an
# already-finished task across loops is legal, which is why this hid so well.
_CURRENT: Optional[SentenceQueue] = None
_current_lock = threading.Lock()


def new_sentence_queue() -> SentenceQueue:
    """Build the queue for a new turn and make it the current one.

    Call once per turn, from the loop that will consume it. The previous
    turn's queue is left alone — it is still draining on its own loop.
    """
    global _CURRENT
    q = SentenceQueue()
    with _current_lock:
        _CURRENT = q
    return q


def get_sentence_queue() -> SentenceQueue:
    """The turn currently speaking, for interrupt() from another thread.

    Builds one if no turn has run yet so that a stray stop/barge-in before the
    first turn is a no-op rather than an AttributeError.
    """
    global _CURRENT
    with _current_lock:
        if _CURRENT is None:
            _CURRENT = SentenceQueue()
        return _CURRENT


def sentence_queue_depth() -> Optional[int]:
    """Current queue depth for diagnostics, or None if no turn has built a
    queue yet. Deliberately does NOT construct the queue — reading a metric
    must not create the thing it measures.
    """
    with _current_lock:
        current = _CURRENT
    return None if current is None else current.depth
