"""T-wake-word-executes-ambient-audio item 2: the follow-up window must be
gated on speech content, not loudness.

Before this: `elif in_followup: if rms > 500` fired a capture on mere
near-silence, which Whisper then hallucinated a whole command out of
("I am working out." ran a full LLM turn). It was also structurally dead
code — the wake branch's `rms > _VAD_RMS_THRESHOLD` (50) catches every
audiible frame first, so the elif could never run. Vosk now feeds both
paths; follow-up additionally requires new decoded speech in the partial.

The gate itself has since changed. `_has_followup_content` asked for
alphabetic words, which cannot work here: the recognizer is built with the
grammar ["onyx", "[unk]"], so everything the user says after the wake
phrase decodes to the literal token "[unk]" — no alphabetic characters.
Probed against the live model on two recorded clips, that function was
False on every frame of real speech and True only on frames containing
"onyx", meaning the follow-up window only ever reopened for a second wake
word. `_partial_grew` replaced it. The tests below keep covering the old
function because it is still the correct check for a free-vocabulary
recognizer and it is still exported — the point is that it is no longer
what gates follow-up.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon.wake_word import _has_followup_content, _partial_grew


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


# ── the gate that is actually wired to the follow-up window ────────────

def test_followup_gate_is_partial_growth():
    """Wiring guard. If this file's function ever goes back to being the
    follow-up gate, the window silently stops reopening on real speech."""
    import inspect
    from backend.daemon import wake_word
    src = inspect.getsource(wake_word.WakeWordListener.listen)
    # Match call forms only — the loop carries a comment naming the old gate
    # to explain why it is gone, and that must not read as a wiring.
    assert "_partial_grew(partial, self._partial_tokens)" in src
    assert "_has_followup_content(" not in src


def test_near_silence_produces_no_growth():
    """The original defect, restated in the terms the gate now uses. Vosk
    keeps returning the accumulated string on silent frames; the token
    count does not move, so no capture starts and Whisper is never handed
    near-silence to hallucinate on."""
    assert not _partial_grew("", 0)
    assert not _partial_grew("[unk]", 1)
    assert not _partial_grew("[unk] [unk] [unk]", 3)


def test_new_speech_produces_growth():
    assert _partial_grew("[unk]", 0)
    assert _partial_grew("[unk] [unk]", 1)
    assert _partial_grew("onyx", 0)