"""STT transcript gate — see T-wake-word-executes-ambient-audio.

The daemon's only pre-dispatch check was an RMS floor, which measures
loudness, not speech. Whisper hallucinating on room tone or on the
assistant's own TTS bleeding back into the mic produced a transcript that
went straight to the router and was executed — that is how ambient audio
launched applications.
"""
import pytest

from backend.daemon.trigger import _is_dispatchable


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "\n\t ",
    ".",
    "...",
    "you",
    "You.",
    "  THANK YOU  ",
    "Thanks for watching",
    "[BLANK_AUDIO]",
    "[silence]",
    "music",
    "[Applause]",
    "Please subscribe",
    "a",
])
def test_non_commands_are_dropped(text):
    assert _is_dispatchable(text) is False, f"{text!r} must not reach the router"


@pytest.mark.parametrize("text", [
    "mute",
    "open notepad",
    "what time is it",
    "volume up",
    "what is the capital of France",
    "take a screenshot",
])
def test_real_commands_pass(text):
    assert _is_dispatchable(text) is True, f"{text!r} is a valid command"


def test_gate_is_case_and_punctuation_insensitive():
    """Whisper punctuates and capitalizes; the gate must see through both."""
    assert _is_dispatchable("Thank you.") is False
    assert _is_dispatchable("THANK YOU!") is False
    assert _is_dispatchable("you?") is False


def test_gate_does_not_over_reject_short_real_commands():
    """'mute' and 'ok' are short but legitimate — the length floor is 2."""
    assert _is_dispatchable("ok") is True
    assert _is_dispatchable("hi") is True


# ── Additions pulled from this install's own archived captures ────────────

def test_the_long_form_youtube_outro_is_dropped():
    """'like and subscribe' was already listed, but matching is
    exact-after-normalise, so the full phrasing still got through and was
    dispatched on 2026-09-13."""
    from backend.daemon.trigger import _is_dispatchable

    assert not _is_dispatchable("Like, comment, share and subscribe.")
    assert not _is_dispatchable("like comment share and subscribe")


def test_onyx_own_stock_lines_are_never_commands():
    """Archived as a transcript on 2026-09-15: the mic heard Onyx itself.
    was_recently_spoken() only covers its own time window; a stock line
    arriving later is still unambiguously echo."""
    from backend.daemon.trigger import _is_dispatchable, _STT_UNAVAILABLE_SPEECH

    assert not _is_dispatchable("I'm sorry I didn't quite understand that")
    for line in _STT_UNAVAILABLE_SPEECH.values():
        assert not _is_dispatchable(line), f"stock line dispatched: {line!r}"


def test_stock_lines_are_derived_not_retyped():
    """If a line is reworded, the filter must follow it automatically."""
    from backend.daemon import trigger

    for line in trigger._STT_UNAVAILABLE_SPEECH.values():
        assert trigger._normalize_fragment(line) in trigger._STT_HALLUCINATIONS


def test_real_commands_still_survive_the_additions():
    from backend.daemon.trigger import _is_dispatchable

    for cmd in ["Onyx open notepad", "what time is it", "open whatsapp",
                "play despacito on youtube", "subscribe to the newsletter",
                "remind me to call mom"]:
        assert _is_dispatchable(cmd), f"real command dropped: {cmd!r}"
