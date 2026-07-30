"""TTS echo suppression — see T-wake-word-executes-ambient-audio, item 1.

The assistant's speech bleeds into the mic, barge-in fires on loudness, Whisper
transcribes the bleed into something plausible, and the router executes it.
_is_dispatchable() only catches self-evident non-commands; a clean transcript of
our own sentence walks straight through it.

These cover the matcher. They do NOT prove the loop is broken in a real room —
see the live probe in the session report for that. A test with a fake mic proves
the function, never the delivery.
"""
import sys
import time
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech import tts_piper
from backend.ai_modules.speech.tts_piper import (
    ECHO_CONTAINMENT_RATIO,
    ECHO_MIN_TOKENS,
    ECHO_TAIL_S,
    _close_utterance,
    _note_spoken,
    was_recently_spoken,
)


@pytest.fixture(autouse=True)
def clean_ring():
    """Each test starts with nothing spoken."""
    tts_piper._recent_spoken.clear()
    yield
    tts_piper._recent_spoken.clear()


def _spoke(text: str, ended_ago: float | None = 0.0):
    """Record `text` as spoken and finished `ended_ago` seconds in the past."""
    u = _note_spoken(text)
    if ended_ago is not None:
        _close_utterance(u)
        u.ended_at = time.monotonic() - ended_ago
    return u


ANSWER = (
    "The weather in Bangalore is twenty six degrees and partly cloudy. "
    "There is a sixty percent chance of rain this evening."
)


# ── Echo it must catch ─────────────────────────────────────────────────

def test_exact_echo_is_suppressed():
    _spoke(ANSWER)
    assert was_recently_spoken(ANSWER) is True


def test_fragment_of_an_utterance_is_suppressed():
    """The mic catches part of a sentence, not the whole answer — this is the
    common shape and the reason matching is containment, not similarity."""
    _spoke(ANSWER)
    assert was_recently_spoken("sixty percent chance of rain this evening") is True


def test_whisper_mangled_echo_is_suppressed():
    """Different casing, punctuation dropped, one word lost to the room."""
    _spoke(ANSWER)
    assert was_recently_spoken("the weather in bangalore is twenty six degrees and cloudy") is True


def test_echo_while_still_speaking_is_suppressed():
    """Not yet closed — barge-in captures land mid-playback."""
    _note_spoken(ANSWER)
    assert was_recently_spoken("there is a sixty percent chance of rain") is True


def test_any_of_several_recent_utterances_can_match():
    """Streamed turns push one utterance per sentence into the ring."""
    _spoke("Opening your calendar now.")
    _spoke("You have three meetings today.")
    _spoke("The first one starts at nine thirty.")
    assert was_recently_spoken("you have three meetings today") is True


def test_capture_spanning_two_sentences_is_suppressed():
    """The mic doesn't respect our sentence boundaries. This transcript is
    half of one utterance and half of the next — it scores ~0.5 against each
    and would survive a per-utterance check."""
    _spoke("You have three meetings today.")
    _spoke("The first one starts at nine thirty.")
    assert was_recently_spoken("three meetings today the first one starts") is True


# ── Speech it must not touch ───────────────────────────────────────────

def test_unrelated_command_passes():
    _spoke(ANSWER)
    assert was_recently_spoken("open notepad and take a note") is False


def test_earlier_sentence_of_a_burst_stays_live():
    """Found by the live probe. A fragment of sentence 2 of a 3-sentence answer
    reached the gate 13s after that sentence ended but only 9s after the
    assistant stopped talking. Per-sentence expiry let a verbatim echo through;
    the ring has to expire as a burst."""
    _spoke("Jupiter is the largest planet in the solar system.", ended_ago=17.0)
    _spoke("It is a gas giant made mostly of hydrogen and helium.", ended_ago=13.0)
    _spoke("The great red spot is a storm larger than the Earth.", ended_ago=9.0)

    assert was_recently_spoken("it is a gas giant made mostly of hydrogen and helium") is True


def test_whole_burst_expires_together():
    _spoke("Jupiter is the largest planet in the solar system.", ended_ago=ECHO_TAIL_S + 8)
    _spoke("It is a gas giant made mostly of hydrogen and helium.", ended_ago=ECHO_TAIL_S + 1)

    assert was_recently_spoken("it is a gas giant made mostly of hydrogen and helium") is False


def test_new_burst_does_not_resurrect_an_ancient_utterance():
    """A fresh sentence keeps the ring live, but not something said minutes ago."""
    _spoke("Your bank balance is four thousand dollars.", ended_ago=300.0)
    _spoke("Anything else?", ended_ago=0.5)

    assert was_recently_spoken("your bank balance is four thousand dollars") is False


def test_expired_window_passes():
    """Same words, past the tail — a valid command a few seconds later."""
    _spoke(ANSWER, ended_ago=ECHO_TAIL_S + 0.5)
    assert was_recently_spoken(ANSWER) is False


def test_nothing_spoken_at_all_passes():
    assert was_recently_spoken("what is the capital of France") is False


def test_short_transcripts_are_never_echo():
    """Real commands are short; coincidental containment is not evidence."""
    _spoke("Opening Chrome.")
    assert was_recently_spoken("open chrome") is False
    _spoke("Turning the volume up.")
    assert was_recently_spoken("volume up") is False


def test_user_repeating_a_narrated_command_is_not_suppressed():
    """The known false-positive risk. The assistant narrates an action in the
    gerund, the user says it in the imperative — that one-token swap is the
    whole signal, so the threshold has to sit above it."""
    _spoke("Playing music on Spotify.")
    assert was_recently_spoken("play music on spotify") is False

    _spoke("I am opening Chrome for you.")
    assert was_recently_spoken("open chrome for me") is False


def test_empty_and_whitespace_pass():
    _spoke(ANSWER)
    assert was_recently_spoken("") is False
    assert was_recently_spoken("   ") is False


# ── The constants are the contract ─────────────────────────────────────

def test_thresholds_are_named_and_sane():
    assert 0.0 < ECHO_CONTAINMENT_RATIO <= 1.0
    assert ECHO_MIN_TOKENS >= 2
    assert ECHO_TAIL_S > 0


def test_ring_is_bounded():
    for i in range(50):
        _spoke(f"utterance number {i} of the stream")
    assert len(tts_piper._recent_spoken) <= tts_piper._RECENT_SPOKEN_CAP


# ── The gate wiring ────────────────────────────────────────────────────

def test_is_dispatchable_stays_pure():
    """The echo check must live outside _is_dispatchable — that function is
    time-independent and 23 cases in test_transcript_gate.py rely on it."""
    from backend.daemon.trigger import _is_dispatchable

    _spoke(ANSWER)
    assert _is_dispatchable(ANSWER) is True, "_is_dispatchable must not consult the clock"


def test_trigger_imports_the_gate():
    from backend.daemon import trigger

    assert trigger.was_recently_spoken is was_recently_spoken
