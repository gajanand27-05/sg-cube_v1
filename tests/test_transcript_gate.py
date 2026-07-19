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
