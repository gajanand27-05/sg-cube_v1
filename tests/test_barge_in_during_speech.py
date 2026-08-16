"""The listener must still hear you while the assistant is speaking.

Reported: "the stop command is not working, i cannot interrupt while its
speaking."

It is not the stop command. `listen()` sets `self._capturing = True`, calls
`on_wake(audio)`, and clears the flag in a `finally`. Every iteration of the
loop starts with `if self._capturing: continue`. And `on_wake` is
`handle_wake`, which runs `asyncio.run(...)` over the whole turn —
`_run_brain_streaming` ends in `await sq.finish()`, which drains the sentence
queue, i.e. it does not return until the last word has been played.

So from wake until the assistant stops talking, every microphone frame is
discarded. Barge-in cannot fire, the wake word cannot be recognised, and
"stop" cannot be heard — there is nothing wrong with any of them, they are
simply never reached. `[TTS] Speech interrupted` still appears in the log
because `on_wake_detected` calls `stop_speech()` unconditionally, which prints
whether or not anything was playing; that is what made this look like
interruption was working.

These tests drive the real loop with a slow on_wake and assert on what the
listener does WHILE it runs.
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

BLOCK_FRAMES = 2000
BLOCK_BYTES = BLOCK_FRAMES * 2


class _NullStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _loud_speech_blocks(n=40):
    """Loud frames. Content does not matter here — these tests are about
    whether the loop LOOKS at frames at all while a turn is in flight."""
    rng = np.random.default_rng(1)
    out = []
    for _ in range(n):
        block = rng.normal(0, 3000, BLOCK_FRAMES)
        out.append(np.clip(block, -32000, 32000).astype(np.int16).tobytes())
    return out


def _make_listener(on_wake, speaking_secs=1.0):
    from backend.daemon import wake_word as ww
    if not (ww.MODELS_DIR / ww.DEFAULT_MODEL).exists():
        pytest.skip("Vosk model not downloaded")
    listener = ww.WakeWordListener(on_wake=on_wake)
    listener._capture = lambda initial=None: b"\x00" * BLOCK_BYTES
    return listener


def _run(listener, blocks, seconds=3.0):
    from backend.core.state import manager
    from backend.daemon import wake_word as ww
    for b in blocks:
        listener.queue.put(b)
    # The loop sets _voice_trigger_source; trigger.py's finally normally
    # clears it, and we stub that half out. Leaving "barge_in" behind silently
    # un-trusts every SYSTEM_WRITE tool in every later test — it has already
    # cost two confusing failures in test_capability_tiers /
    # test_verifier_secondary_check that passed in isolation.
    prev_source = manager._voice_trigger_source
    try:
        with patch.object(ww.sd, "RawInputStream", lambda **kw: _NullStream()):
            t = threading.Thread(target=listener.listen, daemon=True)
            t.start()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                time.sleep(0.05)
            listener._running = False
            t.join(3.0)
    finally:
        manager._voice_trigger_source = prev_source
    return t


def test_frames_are_still_processed_while_a_turn_is_in_flight():
    """The core assertion. While on_wake is running — which is the whole time
    the assistant is speaking — the loop must keep pulling frames off the mic
    queue, or nothing the user says can ever be heard."""
    turn_started = threading.Event()
    release = threading.Event()
    depth_during_turn = []

    listener_box = {}

    def slow_on_wake(audio):
        turn_started.set()
        # Stand in for a turn that speaks for a while.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and not release.is_set():
            time.sleep(0.05)
        depth_during_turn.append(listener_box["l"].queue.qsize())
        return True

    listener = _make_listener(slow_on_wake)
    listener_box["l"] = listener

    # Force the first frame to trigger a turn without needing the wake word.
    listener._check_barge_in = lambda rms, partial="": True
    from backend.core.state import AssistantState, manager
    prev = manager.current
    manager._current_state = AssistantState.SPEAKING
    try:
        _run(listener, _loud_speech_blocks(40), seconds=3.0)
    finally:
        manager._current_state = prev
        release.set()

    assert turn_started.is_set(), "the turn never started; fixture is wrong"
    assert depth_during_turn, "on_wake never completed"
    # If the loop had been blocked, every frame queued after the turn began
    # would still be sitting in the queue when the turn ended.
    assert depth_during_turn[0] < 35, (
        f"{depth_during_turn[0]} frames were still queued when the turn "
        "ended — the listener was deaf for the whole turn, which is why "
        "barge-in and 'stop' cannot work while it is speaking"
    )


def test_capturing_flag_covers_only_the_capture_not_the_whole_turn():
    """`_capturing` gates the `continue` at the top of the loop. It must be
    cleared once the command audio has been read, not held until the
    assistant has finished replying."""
    seen = []

    def slow_on_wake(audio):
        time.sleep(0.6)
        return True

    listener = _make_listener(slow_on_wake)
    listener._check_barge_in = lambda rms, partial="": True

    from backend.core.state import AssistantState, manager
    prev = manager.current
    manager._current_state = AssistantState.SPEAKING

    original_capture = listener._capture

    def watched_capture(initial=None):
        seen.append(("capture", listener._capturing))
        return original_capture(initial)

    listener._capture = watched_capture

    def watched_on_wake(audio):
        seen.append(("on_wake", listener._capturing))
        return slow_on_wake(audio)

    listener.on_wake = watched_on_wake
    try:
        _run(listener, _loud_speech_blocks(10), seconds=2.0)
    finally:
        manager._current_state = prev

    during_capture = [flag for what, flag in seen if what == "capture"]
    during_turn = [flag for what, flag in seen if what == "on_wake"]
    assert during_capture and during_capture[0] is True, (
        "the capture phase must hold _capturing — otherwise the loop races "
        "the capture for the same frames"
    )
    assert during_turn and during_turn[0] is False, (
        "_capturing was still set while the turn ran, so every frame during "
        "the reply is dropped by the `continue` at the top of the loop"
    )


if __name__ == "__main__":
    test_frames_are_still_processed_while_a_turn_is_in_flight()
    print("  [PASS] frames processed during a turn")
    test_capturing_flag_covers_only_the_capture_not_the_whole_turn()
    print("  [PASS] _capturing scoped to the capture")
