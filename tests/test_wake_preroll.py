"""Speech spoken while the wake word is still being recognised must survive.

The listen loop pulls every frame off the mic queue, feeds it to Vosk, and
drops it. Only the frame that triggers is kept — and on the WAKE path not even
that: `initial_audio` stays [] and is only seeded for follow-up and barge-in.
`_capture`'s own docstring says `initial` exists for "audio that arrived during
wake recognition", but nothing ever passed it.

So `_capture` starts reading at the queue's CURRENT position, and everything
between the start of the utterance and the frame where Vosk finally reports
"onyx" is gone.

Measured against the real model on a real recording of this user's voice,
varying the alignment of the wake word against the 125ms block grid:

    lag: min 125ms, median 500ms, max 1625ms  (n=8)

Half a second of the command, routinely, and up to 1.6s. That is the whole
head of a short command, and it matches the reported mis-transcriptions
exactly:

    "can you hear me"  -> 'Hear me on X.'     ("can you" lost)
    "close notepad"    -> 'This is notepad.'  ("close" lost)
"""
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon import wake_word as ww

BLOCK_FRAMES = 2000


def _marked_frame(value: int) -> bytes:
    """A frame whose every sample is `value` — so we can tell which frames
    made it into the capture and which were dropped."""
    return np.full(BLOCK_FRAMES, value, dtype=np.int16).tobytes()


class _FakeRecognizer:
    """Reports the wake word only after `fire_after` frames, standing in for
    Vosk needing several frames of evidence before it will say "onyx"."""

    def __init__(self, fire_after: int):
        self.fire_after = fire_after
        self.seen = 0

    def AcceptWaveform(self, data):
        self.seen += 1
        return False

    def PartialResult(self):
        return '{"partial": "onyx"}' if self.seen >= self.fire_after else '{"partial": ""}'

    def Reset(self):
        self.seen = 0

    def FinalResult(self):
        return '{"text": ""}'


class _NullStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _silent_frame() -> bytes:
    return np.zeros(BLOCK_FRAMES, dtype=np.int16).tobytes()


def _drive_frames(frames, fire_after: int):
    """Feed an explicit list of frames; the wake fires on frame `fire_after`."""
    return _drive(fire_after, frames=frames)


def _drive(fire_after: int, n_frames: int = 12, frames=None):
    """Feed `n_frames` distinctly-marked frames; the wake fires on frame
    `fire_after`. Returns the audio handed to on_wake."""
    import threading
    import time

    captured = {}

    def on_wake(audio):
        captured["audio"] = audio
        return True

    listener = object.__new__(ww.WakeWordListener)
    listener.on_wake = on_wake
    listener.on_wake_detected = None
    listener.on_barge_in = None
    listener.wake_phrase = "onyx"
    listener.sample_rate = 16000
    listener.device = None
    listener.recognizer = _FakeRecognizer(fire_after)
    listener.queue = __import__("queue").Queue()
    listener._running = False
    listener._capturing = False
    listener._barge_in_frames = 0
    listener._partial_tokens = 0
    listener._barge_in_saw_speech = False
    listener._followup_until = 0.0
    listener._empty_in_a_row = 0
    listener._turn_thread = None
    # __init__ is bypassed (it loads a Vosk model), so mirror the state it
    # would have built.
    listener._preroll = __import__("collections").deque(maxlen=ww._PREROLL_FRAMES)

    for f in (frames if frames is not None
              else [_marked_frame(i * 100) for i in range(1, n_frames + 1)]):
        listener.queue.put(f)

    with patch.object(ww.sd, "RawInputStream", lambda **kw: _NullStream()), \
         patch.object(ww, "dogfooding_ledger"), \
         patch.object(ww, "state_manager"):
        t = threading.Thread(target=listener.listen, daemon=True)
        listener._running = True
        t.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and "audio" not in captured:
            time.sleep(0.05)
        listener._running = False
        if listener._turn_thread:
            listener._turn_thread.join(5)
        t.join(3)
    return captured.get("audio")


def _frames_in(audio: bytes) -> set[int]:
    """Which marker values appear in the captured audio."""
    if not audio:
        return set()
    arr = np.frombuffer(audio, dtype=np.int16)
    return {int(v) for v in np.unique(arr)}


def test_speech_before_the_wake_is_recognised_is_not_lost():
    """The bug. Vosk reports "onyx" on frame 5; frames 1-4 were already spoken
    and are the head of the user's command. They must reach Whisper."""
    audio = _drive(fire_after=5, n_frames=12)
    assert audio, "nothing was captured at all"
    present = _frames_in(audio)

    # Frames 3 and 4 arrived while the recognizer was still accumulating
    # evidence — they are speech, and they are what "can you" was.
    assert 400 in present, (
        f"the frame immediately before the wake fired was dropped; "
        f"captured markers: {sorted(present)}"
    )
    assert 300 in present, (
        f"only one frame of pre-roll survived; the measured lag is up to 13 "
        f"frames. captured markers: {sorted(present)}"
    )


def test_the_capture_still_reaches_frames_after_the_wake():
    """Pre-roll must not replace the live capture — the rest of the command
    still has to be read."""
    audio = _drive(fire_after=5, n_frames=12)
    present = _frames_in(audio)
    assert any(v in present for v in (600, 700, 800)), (
        f"nothing after the wake was captured: {sorted(present)}"
    )


def test_a_pause_between_the_wake_word_and_the_command_is_tolerated():
    """The hazard the pre-roll introduces.

    _capture() scans its `initial` chunks and sets speech_seen=True if any are
    loud. The pre-roll IS the wake word, so it is loud — which arms the
    trailing-silence rule immediately, and 800ms of quiet then ends the
    capture. Saying "onyx" ... then the command a beat later would be cut off
    before the command arrived.

    Before the pre-roll existed this could not happen: `initial` was empty on
    the wake path, so the 3s initial-wait applied. The fix must not trade one
    truncation for another.
    """
    frames = (
        [_marked_frame(100)] * 4          # "onyx", loud -> lands in pre-roll
        + [_silent_frame()] * 10          # the user pauses (1.25s of quiet)
        + [_marked_frame(900)] * 4        # ...then says the command
    )
    audio = _drive_frames(frames, fire_after=4)
    present = _frames_in(audio)
    assert 900 in present, (
        "the command spoken after a pause was cut off; the pre-roll armed the "
        f"trailing-silence rule before the user started talking. markers: "
        f"{sorted(present)}"
    )


if __name__ == "__main__":
    test_speech_before_the_wake_is_recognised_is_not_lost()
    test_the_capture_still_reaches_frames_after_the_wake()
    test_a_pause_between_the_wake_word_and_the_command_is_tolerated()
    print("  [PASS] all")
