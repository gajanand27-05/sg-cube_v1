"""Real captures must be saved with their transcripts, and only on request.

Accuracy work has been measured entirely on tools/_stt_corpus: clean
push-to-talk audio scoring CMD 93.3%, while live sessions produce
'Next voice is cuo of nvd.' The failing audio was discarded every time, so
there is nothing to tune against and no way to tell whether a change helped.

Two properties matter more than the saving itself:

  * OFF unless asked. This records a live microphone in someone's home.
  * FAILURES ARE KEPT. Archiving after the content gate would collect only
    the turns that worked — a corpus of successes, which is exactly the one
    that cannot show a regression.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core import capture_archive


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(capture_archive, "enabled", lambda: True)
    return tmp_path


def _audio(seconds=1.0, amplitude=0.3):
    n = int(seconds * capture_archive.SAMPLE_RATE)
    return (np.sin(np.linspace(0, 220 * 2 * np.pi, n)) * amplitude).astype(np.float32)


def test_it_is_off_unless_switched_on(tmp_path, monkeypatch):
    """The default has to be silence. This is a live microphone."""
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(capture_archive, "enabled", lambda: False)
    assert capture_archive.archive(_audio(), "open notepad") is None
    assert list(tmp_path.glob("*")) == []


def test_a_capture_is_saved_with_its_transcript(archive_dir):
    path = capture_archive.archive(_audio(), "open notepad", trigger="wake")
    assert path is not None and path.exists()

    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["transcript"] == "open notepad"
    assert meta["trigger"] == "wake"
    assert meta["seconds"] == pytest.approx(1.0, abs=0.05)


def test_an_empty_transcript_is_still_archived(archive_dir):
    """The most valuable case. A capture that produced nothing is a failure
    worth listening to — dropping it builds a corpus of only successes."""
    path = capture_archive.archive(_audio(), "", dispatched=False)
    assert path is not None
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["transcript"] == ""
    assert meta["dispatched"] is False


def test_the_wav_is_real_16k_mono_pcm(archive_dir):
    """stt_bench and every audio player have to be able to open these
    directly, or the corpus is unusable where it matters."""
    import wave

    path = capture_archive.archive(_audio(), "test")
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert w.getnframes() > 0


def test_float_audio_is_stored_without_clipping_to_silence(archive_dir):
    """The turn carries float32 in [-1, 1]. Writing those bytes straight out
    would save near-silence and the corpus would be worthless."""
    import wave

    path = capture_archive.archive(_audio(amplitude=0.5), "test")
    with wave.open(str(path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    assert np.abs(pcm).max() > 1000, "audio was written as near-silence"


def test_int16_bytes_are_accepted_too(archive_dir):
    """wake_word hands out raw PCM bytes; trigger has float32. Both paths
    must work or archiving silently covers only one of them."""
    raw = (_audio() * 32767).astype(np.int16).tobytes()
    assert capture_archive.archive(raw, "test") is not None


def test_empty_audio_writes_nothing(archive_dir):
    assert capture_archive.archive(np.zeros(0, dtype=np.int16), "x") is None


def test_old_captures_are_pruned(archive_dir, monkeypatch):
    """An unbounded audio log on someone's laptop is a liability."""
    monkeypatch.setattr(capture_archive, "_MAX_CAPTURES", 5)
    for i in range(9):
        capture_archive.archive(_audio(0.05), f"utterance {i}")
    assert len(list(archive_dir.glob("*.wav"))) <= 5
    # Metadata must not outlive its audio, or the corpus gains phantom rows.
    assert len(list(archive_dir.glob("*.json"))) <= 5


def test_a_failure_to_archive_never_breaks_the_turn(monkeypatch, tmp_path):
    """This runs inside the voice turn. Losing a recording is worth strictly
    less than completing the command."""
    monkeypatch.setattr(capture_archive, "enabled", lambda: True)
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR",
                        tmp_path / "nope" / "\0invalid")
    assert capture_archive.archive(_audio(), "open notepad") is None
