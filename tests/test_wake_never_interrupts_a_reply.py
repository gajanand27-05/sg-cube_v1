"""Interim (2026-09-26): while Onyx is speaking, the wake word does not
interrupt it; only the barge-in path can.

That day 15 wakes fired during replies, all loud (rms 1002-2970); transcribed,
14 of their clips hold no "onyx" (one is ambiguous) — Onyx's own voice and
room speech decode as the wake phrase under the two-word grammar. Each one
cut the reply off.

Drives the real listen loop with Vosk stubbed out (runs anywhere): every frame
decodes as "onyx", so only the guard decides what happens.
"""
import threading
import time
from unittest.mock import patch

import numpy as np
import pytest

from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import wake_word as ww


class _NullStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeRecognizer:
    def __init__(self, *a, **k):
        pass

    def Reset(self):
        pass


@pytest.fixture
def listener(tmp_path, monkeypatch):
    (tmp_path / ww.DEFAULT_MODEL).mkdir()
    monkeypatch.setattr(ww, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(ww.vosk, "Model", lambda *a, **k: object())
    monkeypatch.setattr(ww.vosk, "KaldiRecognizer", _FakeRecognizer)
    monkeypatch.setattr(ww, "feed_wake_chunk", lambda rec, data: "onyx")
    monkeypatch.setattr(ww, "is_speaking", lambda: True)
    monkeypatch.setattr(ww.settings, "enable_barge_in", True)
    events = []
    lis = ww.WakeWordListener(on_wake=lambda audio: True,
                              on_wake_detected=lambda: events.append("wake"),
                              on_barge_in=lambda rms: events.append("barge_in"))
    lis._capture = lambda *a, **k: b""
    lis._start_turn = lambda *a, **k: None
    lis.events = events
    prev_state, prev_source = state_manager.current, state_manager._voice_trigger_source
    state_manager._current_state = AssistantState.SPEAKING
    yield lis
    state_manager._current_state = prev_state
    state_manager._voice_trigger_source = prev_source


def _run(lis, n_frames=12, seconds=1.5):
    loud = np.full(ww.WAKE_BLOCKSIZE, 2500, dtype=np.int16).tobytes()  # rms 2500
    for _ in range(n_frames):
        lis._cb(loud, 0, None, None)
    with patch.object(ww.sd, "RawInputStream", lambda **kw: _NullStream()):
        t = threading.Thread(target=lis.listen, daemon=True)
        t.start()
        time.sleep(seconds)
        lis._running = False
        t.join(3.0)


def test_a_loud_wake_during_a_reply_does_nothing(listener):
    listener._check_barge_in = lambda rms, partial="": False
    _run(listener)
    assert listener.events == []


def test_barge_in_still_interrupts_a_reply(listener):
    listener._check_barge_in = lambda rms, partial="": True
    _run(listener, n_frames=1)
    assert listener.events == ["barge_in"]
