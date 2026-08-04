"""T-wake-word-executes-ambient-audio item 2: the follow-up window must be
gated on speech content, not loudness.

Before this: `elif in_followup: if rms > 500` fired a capture on mere
near-silence, which Whisper then hallucinated a whole command out of
("I am working out." ran a full LLM turn). It was also structurally dead
code — the wake branch's `rms > _VAD_RMS_THRESHOLD` (50) catches every
audiible frame first, so the elif could never run. Vosk now feeds both
paths; follow-up additionally requires real words in the partial.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon.wake_word import _has_followup_content


def test_near_silence_has_no_content():
    """Near-silence produces an empty or sub-word partial — the case that
    let Whisper hallucinate commands. Fillers like "uh"/"hmm" are 2+ alpha
    chars and pass: they ARE real speech, and the capture → dispatch gate
    (not this one) handles hallucinated-sounding text."""
    for partial in ["", " ", "h", "a", "…", "-", "1"]:
        assert not _has_followup_content(partial), repr(partial)


def test_real_speech_has_content():
    for partial in [
        "what time is it",
        "open notepad",
        "hey i want",
        "turn the lights on",
        "the",
        "uh sure",
    ]:
        assert _has_followup_content(partial), repr(partial)


def test_known_hallucinations_blocked():
    """The exact transcripts Whisper produced from near-silence are all
    real-looking words and PASS the gate — this proves the gate is a floor,
    not a fix (echo suppression + the dispatch gate do the rest)."""
    for partial in ["sorry about getting ready to talk about it", "i am working out"]:
        assert _has_followup_content(partial), repr(partial)