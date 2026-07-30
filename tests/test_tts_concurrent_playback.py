"""Overlapping speak_stream() calls must not corrupt each other — T-tts-loop-globals.

`handle_wake()` (trigger.py:153) runs `asyncio.run(...)`, a fresh event loop per
capture. `_audio_queue`, `_stop_event` and `_playback_task` were module-level and
nulled in speak_stream's `finally`, so turn B adopted turn A's queue while turn
A's finally pulled the globals out from under it:

    got Future <Task ... _audio_player()> attached to a different loop
    'NoneType' object has no attribute 'put'
    'NoneType' object has no attribute 'set'

Two callers genuinely overlap in production: the wake-word listener thread runs
a turn while an HTTP /voice/say lands on the server loop, and the proactive
handler spawns its own thread with its own `asyncio.run`.

Only the audio *device* is faked here. The loop and state ownership under test
is the real thing — mocking that would mock the bug.
"""
import asyncio
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech import tts_piper


class _FakeChunk:
    """Matches what PiperVoice.synthesize yields."""

    def __init__(self):
        self.audio_int16_array = np.zeros(256, dtype=np.int16)
        self.sample_rate = 22050


class _FakeVoice:
    def __init__(self, chunks: int = 6):
        self.chunks = chunks

    def synthesize(self, text):
        for _ in range(self.chunks):
            yield _FakeChunk()


class _FakeStream:
    """Stands in for sd.OutputStream. Records writes, blocks for no time."""

    opened = 0
    concurrent = 0
    max_concurrent = 0
    _lock = threading.Lock()

    def __init__(self, **kwargs):
        with _FakeStream._lock:
            _FakeStream.opened += 1

    def start(self):
        with _FakeStream._lock:
            _FakeStream.concurrent += 1
            _FakeStream.max_concurrent = max(_FakeStream.max_concurrent,
                                             _FakeStream.concurrent)

    def write(self, data):
        pass

    def stop(self):
        with _FakeStream._lock:
            _FakeStream.concurrent = max(0, _FakeStream.concurrent - 1)

    def close(self):
        pass

    @classmethod
    def reset(cls):
        cls.opened = 0
        cls.concurrent = 0
        cls.max_concurrent = 0


@pytest.fixture(autouse=True)
def fake_audio():
    _FakeStream.reset()
    tts_piper._recent_spoken.clear()
    with patch.object(tts_piper, "_get_voice", return_value=_FakeVoice()), \
         patch.object(tts_piper.sd, "OutputStream", _FakeStream), \
         patch.object(tts_piper.sd, "stop", lambda: None):
        yield
    tts_piper._recent_spoken.clear()


def _run_in_own_loop(text: str, errors: list, barrier: threading.Barrier | None = None):
    """Exactly what handle_wake does: asyncio.run in this thread."""

    async def _speak():
        if barrier is not None:
            # Land both turns inside speak_stream at the same time.
            await asyncio.get_running_loop().run_in_executor(None, barrier.wait)
        async for _ in tts_piper.speak_stream(text):
            await asyncio.sleep(0)

    try:
        asyncio.run(_speak())
    except Exception as e:  # noqa: BLE001 — the failure mode is the assertion
        errors.append(f"{type(e).__name__}: {e}")


def test_two_overlapping_turns_on_separate_loops_do_not_crash():
    """The reproduction. Before the fix this raises 'attached to a different
    loop' / 'NoneType' object has no attribute 'put'."""
    errors: list[str] = []
    barrier = threading.Barrier(2)

    threads = [
        threading.Thread(target=_run_in_own_loop,
                         args=(f"utterance number {i}", errors, barrier))
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a turn hung"
    assert errors == [], f"overlapping turns crashed: {errors}"


def test_many_overlapping_turns_stay_clean():
    """Four concurrent loops — the proactive handler, an HTTP /voice/say and a
    voice turn can all be in flight together."""
    errors: list[str] = []
    barrier = threading.Barrier(4)
    threads = [
        threading.Thread(target=_run_in_own_loop, args=(f"sentence {i} here", errors, barrier))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads)
    assert errors == [], f"crashes: {errors}"


def test_sequential_turns_each_get_their_own_state():
    """The normal case must keep working: each turn plays to completion."""
    errors: list[str] = []
    for i in range(3):
        _run_in_own_loop(f"turn {i} speaking now", errors)
    assert errors == []
    assert _FakeStream.opened == 3, "each turn should open its own stream"


def test_stop_speech_is_safe_with_nothing_playing():
    tts_piper.stop_speech()  # must not raise


def test_stop_speech_from_another_thread_ends_playback():
    """Barge-in calls stop_speech() from the wake-word listener thread while
    playback runs on a different loop. It must take effect, not raise."""
    errors: list[str] = []
    started = threading.Event()
    finished = threading.Event()

    async def _speak():
        async for progress in tts_piper.speak_stream("a fairly long utterance to interrupt"):
            if progress.get("status") == "playing":
                started.set()
            await asyncio.sleep(0.01)

    def _run():
        try:
            asyncio.run(_speak())
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
        finally:
            finished.set()

    t = threading.Thread(target=_run)
    t.start()
    assert started.wait(timeout=10), "playback never started"
    tts_piper.stop_speech()          # from this thread, not the playback loop
    assert finished.wait(timeout=10), "stop_speech did not end playback"
    t.join(timeout=5)

    assert errors == [], f"stop_speech across threads raised: {errors}"


def test_is_speaking_reports_false_once_everything_finishes():
    errors: list[str] = []
    _run_in_own_loop("all done here", errors)
    assert errors == []
    assert tts_piper.is_speaking() is False
