"""The follow-up capture should keep its head without swallowing our own TTS.

Measured against a real recording of a live session: the follow-up path lost
880ms of the user's words.

    you said        "Introduce yourself."      -> [command] 'yourself'
    you said        "I need to send a whatsapp
                     message to Sharath"       -> [command] 'to send a whatsapp...'

Cause: the wake branch seeds the capture with `list(self._preroll)` (13 frames,
1.625s), but the follow-up branch seeds it with `[data]` — a single 125ms
frame. Everything spoken while Vosk was still accumulating evidence is gone.

Handing the follow-up path the whole pre-roll is NOT safe on its own, because
the pre-roll keeps filling during playback: `_capturing` is cleared before the
turn body runs, so the listen loop keeps appending frames while Onyx speaks.
There is no acoustic echo cancellation anywhere in the tree. Contaminated
transcripts break the echo gate in BOTH directions, measured:

    "How can I help you today? Introduce yourself."  -> passes, planner sees both
    "...I've got you covered. ... Yes."              -> DROPPED as echo

The second is the dangerous one: a bare "yes" is exactly the shape of a
confirmation answer for a DESTRUCTIVE tool.

So the pre-roll is trimmed per frame against the moment playback ended.

Frame timestamps are stamped in the mic CALLBACK, not at dequeue: a dequeue
timestamp marks the end of the frame's 125ms plus queue delay, so a frame that
looks late can still START inside the TTS tail. PortAudio's own
`inputBufferAdcTime` would be ideal but is measured as ZERO on every callback
on this machine (MME host API), so frame start is derived:

    start = callback_time - blocksize/samplerate - stream.latency
          = callback_time - 0.125 - 0.125          (measured on this device)

Both terms are reported or derived — no new acoustic constant. Subtracting the
latency biases `start` EARLIER, which makes `start > boundary` harder to pass,
so the error direction is "drop a clean frame", never "keep a dirty one". That
also covers the +/-16ms callback jitter measured on MME.
"""
import math
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import tts_piper
from backend.daemon import wake_word as ww

TTS = b"\x11\x11" * 1000          # stands in for a frame of Onyx's own voice
USER = b"\x22\x22" * 1000         # stands in for a frame of the user's voice


def test_frames_after_playback_ended_are_kept():
    """The head of the utterance. This is the 880ms that was being lost."""
    frames = [(10.0, TTS), (10.5, TTS), (11.0, USER), (11.125, USER)]
    assert ww.clean_preroll(frames, boundary=10.9) == [USER, USER]


def test_frames_from_during_playback_are_dropped():
    """Onyx's own voice must never reach STT."""
    frames = [(10.0, TTS), (10.5, TTS)]
    assert ww.clean_preroll(frames, boundary=10.9) == []


def test_a_frame_straddling_the_boundary_is_dropped():
    """A frame that STARTS before playback ended still contains TTS in its
    first samples, however late it finishes. The test is on frame start, so
    this drops — the conservative direction."""
    straddling_start = 10.85          # ends at 10.975, after the boundary
    frames = [(straddling_start, TTS), (11.0, USER)]
    kept = ww.clean_preroll(frames, boundary=10.9)
    assert TTS not in kept, "a frame that began during playback survived the trim"
    assert kept == [USER]


def test_nothing_is_kept_while_still_speaking():
    """`speech_boundary()` reports +inf during playback, so every frame fails
    the test and the capture falls back to the triggering frame alone."""
    frames = [(10.0, USER), (11.0, USER)]
    assert ww.clean_preroll(frames, boundary=math.inf) == []


def test_everything_is_kept_when_nothing_was_ever_spoken():
    """-inf means the ring is empty — a first-ever turn has no TTS to avoid,
    and must not be punished with a truncated head."""
    frames = [(10.0, USER), (11.0, USER)]
    assert ww.clean_preroll(frames, boundary=-math.inf) == [USER, USER]


# ── the boundary itself ────────────────────────────────────────────────


def test_speech_boundary_is_infinite_while_speaking(monkeypatch):
    """Still talking: no captured frame can be trusted."""
    monkeypatch.setattr(tts_piper, "_recent_spoken",
                        tts_piper.deque([tts_piper._Utterance(
                            text="hello", tokens=("hello",),
                            started_at=tts_piper.time.monotonic())]))
    assert tts_piper.speech_boundary() == math.inf


def test_speech_boundary_is_negative_infinite_when_nothing_spoken(monkeypatch):
    monkeypatch.setattr(tts_piper, "_recent_spoken", tts_piper.deque())
    assert tts_piper.speech_boundary() == -math.inf


def test_speech_boundary_uses_the_last_utterance_not_an_intermediate_one(monkeypatch):
    """Streaming TTS closes sentence 1 while 2..N are still queued. Trimming
    against sentence 1's end would admit every later sentence's audio."""
    def _closed(text, started, ended):
        u = tts_piper._Utterance(text=text, tokens=(text,), started_at=started)
        u.ended_at = ended
        return u

    monkeypatch.setattr(tts_piper, "_recent_spoken", tts_piper.deque([
        _closed("first sentence.", 100.0, 102.0),
        _closed("second sentence.", 102.0, 104.0),
        _closed("last sentence.", 104.0, 106.5),
    ]))
    assert tts_piper.speech_boundary() == 106.5


# ── wiring ─────────────────────────────────────────────────────────────


def test_the_followup_branch_actually_trims_the_preroll():
    """Wiring guard. A trim that is computed and never used would leave the
    880ms loss exactly where it was — and this whole file passing."""
    import inspect

    src = inspect.getsource(ww.WakeWordListener.listen)
    followup = src[src.index("elif (in_followup"):]
    followup = followup[:followup.index("except Exception")]
    assert "clean_preroll" in followup, (
        "the follow-up branch still seeds the capture with the trigger frame "
        "alone; the head of the utterance is still being discarded"
    )


def test_frames_are_stamped_in_the_callback_not_at_dequeue():
    """A dequeue timestamp marks the END of the frame plus queue delay, so a
    frame stamped after `ended_at` can still begin inside the TTS tail."""
    import inspect

    src = inspect.getsource(ww.WakeWordListener._cb)
    assert "monotonic" in src, (
        "_cb no longer stamps frames; whoever dequeues them cannot recover "
        "when the audio was actually captured"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
