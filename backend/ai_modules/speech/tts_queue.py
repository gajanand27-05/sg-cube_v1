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
        # The loop `_queue` and `_task` belong to, captured in start(). Needed
        # because interrupt() is called from the wake-word listener THREAD and
        # must not touch either of them directly — see interrupt().
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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
        self._loop = asyncio.get_running_loop()
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

        Safe to call from any task OR THREAD. Idempotent.

        The queue work is deliberately not done inline. interrupt() is called
        from the wake-word listener thread (on_wake_detected / on_barge_in),
        and asyncio.Queue is not thread-safe: put_nowait wakes a parked getter
        by completing that getter's future, which posts the wakeup with
        `call_soon`. Unlike `call_soon_threadsafe`, call_soon does not write to
        the loop's self-pipe — so a loop asleep in select() never learns about
        it and the consumer stays parked until some unrelated timer fires.

        Measured in tests/test_interrupted_turn_ends_quietly.py: an interrupt
        raised at t=0.2s was not noticed until t=3.0s, when the next timer
        happened to come due. That latency is paid by the NEXT turn, which
        sits in wake_word._start_turn's handover join until it gives up:

            [wake] previous turn still running after 15s; starting anyway

        `_interrupted` is set here rather than in the callback so enqueue()
        starts refusing late sentences immediately, whenever the loop gets
        around to running.
        """
        if self._interrupted:
            return
        self._interrupted = True
        # Kill Piper's current playback synchronously. This one IS thread-safe
        # (a threading.Event plus sd.stop) and it is the part that has to be
        # immediate — it is what actually stops audio coming out of the
        # speaker while the user is talking over it.
        try:
            stop_speech()
        except Exception as e:
            log.warning(f"stop_speech raised during interrupt: {e}")

        loop = self._loop
        if loop is None:
            # start() was never called, so there is no queue anyone is waiting
            # on and nothing to schedule onto.
            self._drain_and_close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            # Already on the owning loop — run it inline so callers that
            # interrupt and immediately assert on the queue still see it
            # drained, rather than one loop iteration later.
            self._drain_and_close()
            return
        try:
            loop.call_soon_threadsafe(self._drain_and_close)
        except RuntimeError:
            # Loop already closed — the turn that owned this queue is over,
            # which is the outcome interrupt() wanted anyway.
            pass

    def _drain_and_close(self) -> None:
        """Discard pending sentences and poke the consumer. Owning loop only."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # Sentinel so the consumer exits even if it is parked on queue.get().
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
    """Build the queue for a new turn, make it current, and silence the old one.

    Call once per turn, from the loop that will consume it.

    This used to leave the outgoing queue alone, "still draining on its own
    loop". Ownership was the only thing on its mind, and ownership alone stops
    the cross-loop crash while leaving the user listening to two answers:

        [wake] previous turn still running after 15s; starting anyway
        [ai] response: It sounds like you're thinking out loud... (27032ms)
        [ai] response: Sounds good! I'll be here whenever you need me. (6408ms)

    Two turn bodies reached the speak stage, and the old turn's consumer was
    still pulling sentences. tts_piper._activate is "newest wins" per SENTENCE,
    not per turn, so the two drains interleave — each sentence cutting off the
    other turn's — and the answers arrive chopped together. Worse, _activate
    only SETS the previous session's stop Event; `_audio_player` sits inside a
    blocking `stream.write()` and cannot observe it until that write returns,
    so a second sd.OutputStream opens while the first is still feeding the
    device and the mixer plays both at once.

    The handover timeout is not the thing to fix — it is a deliberate safety
    valve so a wedged turn cannot deafen the listener forever, which keeps
    overlap reachable by design. So the speaking side has to be correct under
    overlap, and taking over `_CURRENT` is precisely the moment the outgoing
    turn stops being the turn that speaks.

    Interrupting OUTSIDE the lock on purpose: interrupt() calls stop_speech()
    and may hop loops via call_soon_threadsafe, and holding a module lock
    across that buys nothing and risks everything. `previous` is already safely
    captured by then.
    """
    global _CURRENT
    q = SentenceQueue()
    with _current_lock:
        previous = _CURRENT
        _CURRENT = q
    if previous is not None and previous is not q:
        # Idempotent, so a turn that already ended cleanly costs nothing here.
        try:
            previous.interrupt()
        except Exception as e:      # a handover must never kill the new turn
            log.warning(f"could not silence the outgoing turn: {e}")
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
