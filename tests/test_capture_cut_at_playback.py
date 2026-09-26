"""A capture ends where Onyx starts speaking (unless it is a barge-in).

Measured 2026-09-26: a wake fired while the previous turn was still THINKING,
its capture ran on to the 10s cap straight through the reply, and

    "Good morning, good morning. ... It certainly is. How can I help you
     start your day?"

was dispatched as the user's words. There is no echo cancellation, so every
frame after playback begins holds Onyx's voice; what came before it is still
the user's command and is kept.

The real-recording test reads the user's own capture from a local path and is
skipped when it is missing — the .wav holds the user's voice and is never
committed. The synthetic tests run everywhere.
"""
import math
import os
import queue
import wave
from collections import deque
from pathlib import Path

import numpy as np
import pytest

from backend.ai_modules.speech import tts_piper
from backend.daemon import wake_word as ww

SR = 16000
FRAME_S = ww.WAKE_BLOCKSIZE / SR  # 0.125s, as the live stream delivers it


def _listener(frames):
    lis = object.__new__(ww.WakeWordListener)
    lis.sample_rate = SR
    lis.queue = queue.Queue()
    for f in frames:
        lis.queue.put(f)
    return lis


@pytest.fixture
def spoken(monkeypatch):
    """Isolated TTS history; returns a helper that records 'we started
    speaking at t'."""
    monkeypatch.setattr(tts_piper, "_recent_spoken", deque(maxlen=16))

    def at(t: float):
        tts_piper._recent_spoken.append(
            tts_piper._Utterance(text="reply", tokens=("reply",), started_at=t))
    return at


def _loud(value: int) -> bytes:
    # Loud enough to count as speech for every capture threshold.
    return np.full(ww.WAKE_BLOCKSIZE, value, dtype=np.int16).tobytes()


USER, ONYX = _loud(3000), _loud(9000)


def _frames(t0: float, n_user: int, n_onyx: int):
    out = [(t0 + i * FRAME_S, USER) for i in range(n_user)]
    return out + [(t0 + (n_user + i) * FRAME_S, ONYX) for i in range(n_onyx)]


# ── synthetic (CI) ───────────────────────────────────────────────────────

def test_capture_stops_where_playback_starts(spoken):
    spoken(100.0 + 8 * FRAME_S)  # Onyx starts after 8 frames of the user
    lis = _listener(_frames(100.0, n_user=8, n_onyx=20))
    audio = lis._capture(initial=[USER], cut_at_playback_after=100.0)
    assert audio == USER * 9  # the pre-roll frame + all 8 user frames, no Onyx


def test_a_frame_straddling_playback_start_is_dropped(spoken):
    spoken(100.0 + 2.5 * FRAME_S)  # playback begins mid-frame 2
    lis = _listener(_frames(100.0, n_user=3, n_onyx=5))
    audio = lis._capture(initial=[], cut_at_playback_after=100.0)
    assert audio == USER * 2


def test_speech_that_began_before_the_trigger_does_not_cut(spoken):
    """Only playback STARTING after the trigger ends the capture."""
    spoken(50.0)
    lis = _listener(_frames(100.0, n_user=6, n_onyx=0))
    assert lis._capture(initial=[], cut_at_playback_after=100.0) == USER * 6


def test_barge_in_is_not_cut(spoken):
    """cut_at_playback_after=None is what listen() passes for a barge-in."""
    spoken(100.0)
    lis = _listener(_frames(100.0, n_user=4, n_onyx=0))
    assert lis._capture(initial=[], cut_at_playback_after=None) == USER * 4


def test_no_playback_leaves_the_capture_alone(spoken):
    lis = _listener(_frames(100.0, n_user=5, n_onyx=0))
    assert tts_piper.speech_onset_after(100.0) == math.inf
    assert lis._capture(initial=[], cut_at_playback_after=100.0) == USER * 5


# ── the user's real recording (local only) ───────────────────────────────

REAL = Path(os.environ.get(
    "SG_CUBE_ECHO_WAV",
    Path(__file__).resolve().parents[1] / "backend" / "database" / "captures"
    / "20260926-203822-160.wav"))
# From that session's log: the 1.625s wake pre-roll, then queued frames from
# the wake at 20:38:12.237; the reply started (SPEAKING) at 20:38:14.153.
PREROLL_FRAMES = 13
ONSET_AFTER_TRIGGER_S = 14.153 - 12.237


@pytest.mark.skipif(not REAL.exists(), reason="the user's local capture is not present")
def test_real_echo_capture_keeps_the_user_and_drops_the_reply(spoken):
    with wave.open(str(REAL)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    frames = [pcm[i:i + ww.WAKE_BLOCKSIZE].tobytes()
              for i in range(0, len(pcm), ww.WAKE_BLOCKSIZE)]
    initial, rest = frames[:PREROLL_FRAMES], frames[PREROLL_FRAMES:]
    spoken(ONSET_AFTER_TRIGGER_S)
    lis = _listener([(i * FRAME_S, f) for i, f in enumerate(rest)])

    audio = np.frombuffer(lis._capture(initial=initial, cut_at_playback_after=0.0), np.int16)

    seconds = len(audio) / SR
    assert 3.0 <= seconds <= 3.6, seconds  # was 10.0s, the hard cap
    # The reply reached the mic 3-8x louder than the user's voice: every
    # half-second after the cut peaks above 4000, nothing before it does.
    half = SR // 2
    rms = lambda a: float(np.sqrt(np.mean(a.astype(np.float32) ** 2)))
    kept = [rms(audio[i:i + half]) for i in range(0, len(audio), half)]
    assert max(kept) < 4000, kept
    assert max(rms(pcm[i:i + half]) for i in range(len(audio), len(pcm), half)) > 6000
