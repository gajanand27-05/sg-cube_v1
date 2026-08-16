"""Two turns must never execute at once.

b8e379a moved the turn body onto a worker thread so the listen loop could keep
reading the mic while the assistant speaks — without that, barge-in, the wake
word and "stop" are all unreachable. But handle_wake runs asyncio.run() per
capture, so overlapping turns each get their OWN event loop, and SentenceQueue
is a module-level singleton: start() binds a fresh queue AND a consumer task to
the calling loop, then a second turn overwrites `_task` while the first is
still awaiting it.

Live consequence, roughly one turn in four:

    [ai] Brain error: Task <... _handle_wake_async()> got Future
         <Task ... SentenceQueue._consumer()> attached to a different loop
    [ai] -> Sorry, I encountered an error

plus "await wasn't used with future" and "async generator ignored
GeneratorExit" at shutdown.

The commit that introduced it claimed overlapping turns were survivable
because "playback state is per-call, see T-tts-loop-globals". That was true of
tts_piper._PlaybackSession and false of SentenceQueue. Turn BODIES are now
serialized; the listen loop is deliberately not.
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon import wake_word as ww


def _listener(on_wake):
    listener = object.__new__(ww.WakeWordListener)
    listener.on_wake = on_wake
    listener.wake_phrase = "onyx"
    listener._turn_thread = None
    listener._followup_until = 0.0
    listener._empty_in_a_row = 0
    return listener


def test_turns_do_not_overlap():
    """The invariant. If two turn bodies run at once they share SentenceQueue
    across two event loops and the turn dies."""
    concurrent = []
    live = {"n": 0}
    lock = threading.Lock()

    def on_wake(audio):
        with lock:
            live["n"] += 1
            concurrent.append(live["n"])
        time.sleep(0.25)
        with lock:
            live["n"] -= 1
        return True

    listener = _listener(on_wake)
    with patch.object(ww, "dogfooding_ledger"):
        for _ in range(4):
            listener._start_turn(b"")
            time.sleep(0.02)   # triggers arriving faster than turns complete
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and listener._turn_thread.is_alive():
            time.sleep(0.05)
        listener._turn_thread.join(5)

    assert concurrent, "no turn ran"
    assert max(concurrent) == 1, (
        f"up to {max(concurrent)} turns ran at once; each gets its own "
        "asyncio.run() loop and they share the SentenceQueue singleton"
    )
    assert len(concurrent) == 4, f"expected 4 turns, saw {len(concurrent)}"


def test_the_listen_loop_is_not_what_waits():
    """The join must happen inside the worker. Joining on the caller would
    block the listen loop, which is precisely the deafness b8e379a removed."""
    started = threading.Event()

    def on_wake(audio):
        started.set()
        time.sleep(0.4)
        return True

    listener = _listener(on_wake)
    with patch.object(ww, "dogfooding_ledger"):
        listener._start_turn(b"")
        started.wait(2)
        # A second trigger while the first turn is mid-flight: the CALLER must
        # return immediately even though the new turn will wait its turn.
        t0 = time.perf_counter()
        listener._start_turn(b"")
        caller_ms = (time.perf_counter() - t0) * 1000
        listener._turn_thread.join(10)

    assert caller_ms < 100, (
        f"_start_turn blocked its caller for {caller_ms:.0f}ms; the listen "
        "loop calls this, and blocking it means the mic stops being read"
    )


def test_a_wedged_turn_does_not_deafen_us_forever():
    """Bounded wait. Dropping the user's command is worse than the risk of
    proceeding, so the handover times out rather than blocking forever."""
    assert ww._TURN_HANDOVER_TIMEOUT_S <= 30, (
        "handover timeout is long enough to look like a hang"
    )

    release = threading.Event()
    ran = []

    def on_wake(audio):
        if not ran:
            ran.append("first")
            release.wait(30)          # wedged
        else:
            ran.append("second")
        return True

    listener = _listener(on_wake)
    try:
        with patch.object(ww, "dogfooding_ledger"), \
             patch.object(ww, "_TURN_HANDOVER_TIMEOUT_S", 0.3):
            listener._start_turn(b"")
            time.sleep(0.1)
            listener._start_turn(b"")
            listener._turn_thread.join(5)
        assert "second" in ran, "the second turn never ran behind a wedged one"
    finally:
        release.set()


def test_a_raising_turn_still_hands_over():
    """An exception in one turn must not strand the next one waiting."""
    ran = []

    def on_wake(audio):
        ran.append(1)
        if len(ran) == 1:
            raise RuntimeError("turn exploded")
        return True

    listener = _listener(on_wake)
    with patch.object(ww, "dogfooding_ledger"):
        listener._start_turn(b"")
        time.sleep(0.1)
        listener._start_turn(b"")
        listener._turn_thread.join(5)
    assert len(ran) == 2, f"second turn did not run after the first raised: {ran}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
