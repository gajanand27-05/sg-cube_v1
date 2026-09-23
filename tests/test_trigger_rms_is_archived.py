"""Record what the follow-up gate measured, so it can be calibrated later.

`_FOLLOWUP_MIN_RMS = 400` was set from one session's observations (false
triggers at 64-203, real speech at 975-2908) and a live false trigger has
since been seen at 478, inside the untested gap. Calibrating it needs the
number the gate actually compares — the RMS of the ONE 125ms trigger frame.

That number was not archived. Command captures recorded transcript, trigger,
dispatched, seconds, recorded_at and nothing else, so the 38 archived
follow-ups cannot say what fired them.

Recomputing it from the WAV would be wrong, and wrong in the direction that
already caused a retraction: the gate sees one 125ms frame, the file is a 10s
capture that is mostly silence, so whole-file RMS reads several dB low and
would push the floor DOWN. Same mistake as the retracted "mic is 10dB low".

Three things beyond the raw number, all needed to read it honestly:

  * the FLOOR IN FORCE, stored per record. The archived sample is censored at
    400 — nothing below it ever becomes a record — so a later analysis would
    otherwise read a truncated distribution as the whole population of
    follow-up attempts.
  * the REJECTIONS, counts only, no audio. Passing triggers alone can only
    show what RAISING the floor would cost; they say nothing about how much
    real speech 400 already drops.
  * rms, transcript and audio path in ONE record, so it can be sorted by rms
    and listened to in order. `dispatched` is NOT a label for "addressed to
    Onyx" — every turn in the 2026-09-22 log dispatched and none of them were
    addressed to it, so ground truth has to come from listening.

Recording only. No gate or threshold changes.
"""
import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import capture_archive as ca
from backend.daemon import wake_word as ww


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(ca, "enabled", lambda: True)
    ca.take_trigger_context()          # clear any leakage
    yield tmp_path
    ca.take_trigger_context()


# ── the trigger context ────────────────────────────────────────────────


def test_trigger_context_round_trips_and_clears():
    ca.set_trigger_context(rms=1234.0, followup_min_rms=400)
    got = ca.take_trigger_context()
    assert got["rms"] == 1234.0 and got["followup_min_rms"] == 400
    assert ca.take_trigger_context() == {}, "context survived being taken"


def test_trigger_context_is_thread_local():
    """NOT a module global. Turn bodies are serialized only up to
    _TURN_HANDOVER_TIMEOUT_S; past it two turns run on two threads. A module
    global raced exactly this way before — `_voice_trigger_source` was read on
    a worker thread after another turn had reset it, and silently mislabelled
    records. handle_wake runs asyncio.run on the turn's own thread, so a
    thread-local reaches the archive call without that hazard.
    """
    seen = {}
    ca.set_trigger_context(rms=111.0)

    def other():
        seen["before"] = ca.take_trigger_context()
        ca.set_trigger_context(rms=222.0)
        seen["after"] = ca.take_trigger_context()

    t = threading.Thread(target=other)
    t.start()
    t.join(5)

    assert seen["before"] == {}, "a worker thread saw another turn's context"
    assert seen["after"]["rms"] == 222.0
    assert ca.take_trigger_context()["rms"] == 111.0, "our own context was eaten"


# ── one record, sortable and playable ──────────────────────────────────


def test_the_record_carries_rms_floor_transcript_and_audio(archive_dir):
    ca.set_trigger_context(rms=478.0, followup_min_rms=ww._FOLLOWUP_MIN_RMS)
    wav = ca.archive(np.zeros(1600, dtype=np.int16), "open notepad",
                     trigger="followup", dispatched=True,
                     extra=ca.take_trigger_context())
    assert wav is not None
    rec = json.loads(wav.with_suffix(".json").read_text())

    assert rec["rms"] == 478.0
    assert rec["followup_min_rms"] == 400, (
        "the floor in force is missing; the sample is censored at it and a "
        "later analysis would read a truncated distribution as the whole "
        "population"
    )
    assert rec["transcript"] == "open notepad"
    assert rec["audio"] == wav.name, (
        "the record does not name its own audio, so it cannot be sorted by "
        "rms and played in order"
    )


def test_a_capture_with_no_trigger_context_still_archives(archive_dir):
    """The text path and the proactive path have no listener behind them."""
    wav = ca.archive(np.zeros(1600, dtype=np.int16), "hi", trigger="")
    assert wav is not None
    rec = json.loads(wav.with_suffix(".json").read_text())
    assert "rms" not in rec and rec["audio"] == wav.name


def test_the_trigger_path_passes_the_context_to_the_archive():
    """Wiring guard: a context set and never read records nothing."""
    import inspect

    from backend.daemon import trigger as tr

    src = inspect.getsource(tr._handle_wake_async)
    assert "take_trigger_context" in src, (
        "the turn archives without the listener's measurement, so the rms is "
        "still missing from every command capture"
    )


# ── rejections, counts only ────────────────────────────────────────────


def test_rejections_are_counted_with_no_audio(archive_dir):
    for rms in (64, 106, 178, 197, 203, 262, 380):
        ca.record_gate_rejection(rms, floor=400)

    assert not list(archive_dir.glob("*.wav")), (
        "a rejection wrote audio — this is a counts-only histogram, and the "
        "rejected frames are by definition the quiet ones nobody wants 970 "
        "files of"
    )
    hist = json.loads((archive_dir / ca.GATE_REJECTIONS_FILE).read_text())
    assert hist["total"] == 7
    assert hist["floor"] == 400, "the histogram does not say what it was below"
    assert sum(hist["bins"].values()) == 7


def test_rejection_counts_accumulate_across_calls(archive_dir):
    ca.record_gate_rejection(150, floor=400)
    ca.record_gate_rejection(150, floor=400)
    hist = json.loads((archive_dir / ca.GATE_REJECTIONS_FILE).read_text())
    assert hist["total"] == 2
    assert hist["bins"]["100"] == 2, hist["bins"]


def test_recording_a_rejection_never_raises(monkeypatch):
    """Runs inside the listen loop. Losing a statistic is worth strictly less
    than continuing to listen."""
    monkeypatch.setattr(ca, "_ARCHIVE_DIR", Path("/nonexistent\x00/bad"))
    ca.record_gate_rejection(100, floor=400)      # must not raise


# ── the gate itself is UNCHANGED ───────────────────────────────────────


def test_the_floor_is_untouched():
    assert ww._FOLLOWUP_MIN_RMS == 400, (
        "tonight is a recording session; the threshold moves only once there "
        "is archived evidence to move it with"
    )


@pytest.mark.parametrize("rms,expected", [(399, False), (400, True), (478, True)])
def test_the_gate_decision_is_unchanged(rms, expected):
    listener = object.__new__(ww.WakeWordListener)
    assert listener._followup_trigger_allowed(rms) is expected


def test_a_rejected_frame_is_counted_and_still_rejected(archive_dir, monkeypatch):
    """Both halves at once: the statistic is recorded AND the gate still says
    no. A counter that changed the decision would be a gate change."""
    listener = object.__new__(ww.WakeWordListener)
    assert listener._followup_trigger(rms=203.0) is False
    hist = json.loads((archive_dir / ca.GATE_REJECTIONS_FILE).read_text())
    assert hist["total"] == 1


def test_a_passing_frame_is_not_counted_as_a_rejection(archive_dir):
    listener = object.__new__(ww.WakeWordListener)
    assert listener._followup_trigger(rms=1208.0) is True
    assert not (archive_dir / ca.GATE_REJECTIONS_FILE).exists(), (
        "a frame that PASSED was counted as a rejection, which would bias the "
        "histogram toward the exact conclusion it exists to test"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
