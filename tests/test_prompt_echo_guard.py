"""Whisper must never hand back its own initial_prompt as a transcript.

Reported live. The user said "play mungaru male music on youtube" and got:

    [command] 'I am talking to my voice assistant, which is called Onyx.'

That is the first sentence of _COMMAND_PROMPT, verbatim. Not a mishearing —
Whisper emits its conditioning text when the audio does not decode, and
"Mungaru Male" is Kannada being force-decoded as English (language="en"), so
there was nothing for it to latch onto.

An earlier, milder version of this was visible and underweighted: a noisy
clip came back 'i am using a closed notepad.', which is the OLD prompt's
opening ("I am using a...") fused with a real word.

Two defences, because either alone is thin:

  1. The prompt no longer contains first-person sentences. A keyword list
     conditions the decoder just as well and does not read like something a
     person said, so there is far less for the model to emit whole.
  2. A guard drops any transcript that is a long verbatim run from the
     prompt. This is the backstop: it holds even if someone rewrites the
     prompt into prose again.

The guard's danger is over-firing. The prompt deliberately lists real
commands ("open notepad", "what time is it"), so a naive containment check
would silently swallow genuine speech. Hence the length floor, and the tests
below pinning real commands as NOT echoes.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech.stt_whisper import _COMMAND_PROMPT, is_prompt_echo


def test_the_reported_sentence_can_no_longer_be_produced():
    """The reported echo — 'I am talking to my voice assistant, which is
    called Onyx.' — was the prompt's own opening line. Defence 1 removed it,
    so the decoder has nothing to copy. Asserting is_prompt_echo() rejects
    that exact string would test the OLD prompt and pass for the wrong
    reason; what matters is that the sentence is gone from the source."""
    assert "talking to my voice assistant" not in _COMMAND_PROMPT.lower()


def test_an_echo_of_the_CURRENT_prompt_is_rejected():
    """Defence 2, on the prompt as it stands now."""
    opening = " ".join(_COMMAND_PROMPT.split()[:10])
    assert is_prompt_echo(opening), opening


def test_any_long_run_from_the_prompt_is_rejected():
    """Not just the opening — whatever part the decoder latches onto."""
    words = _COMMAND_PROMPT.split()
    for start in (0, 5, 12):
        run = " ".join(words[start:start + 12])
        if len(run.split()) >= 8:
            assert is_prompt_echo(run), run


@pytest.mark.parametrize("command", [
    "open notepad",
    "close chrome",
    "what time is it",
    "whats the weather",
    "lock the screen",
    "play music on youtube",
    "set a reminder",
    "play mungaru male music on youtube",
    "who won the twenty twenty four t twenty world cup",
    "find the official nvidia dgx spark documentation",
    "remind me to call mom at six",
])
def test_real_commands_are_never_treated_as_echoes(command):
    """The prompt names real commands on purpose. Swallowing them would be a
    far worse bug than the one this guards — it would drop working speech
    silently, with no error anywhere."""
    assert not is_prompt_echo(command), command


def test_short_input_is_never_an_echo():
    """Short utterances share words with the prompt by coincidence. The floor
    is what keeps the guard from eating them."""
    for text in ("stop", "onyx", "cancel", "open notepad", "be quiet"):
        assert not is_prompt_echo(text), text


def test_empty_input_is_not_an_echo():
    for text in ("", "   ", None):
        assert not is_prompt_echo(text)


def test_punctuation_and_case_do_not_hide_an_echo():
    """Whisper punctuates and capitalises its output, so a byte-comparison
    against the prompt would miss every real echo."""
    run = " ".join(_COMMAND_PROMPT.split()[:10])
    assert is_prompt_echo(run.upper() + "!")
    assert is_prompt_echo(run.lower().replace(",", ""))


# ── the prompt itself ────────────────────────────────────────────────────

def test_the_prompt_has_no_first_person_sentences():
    """Defence 1. First-person prose is what the decoder emitted whole; a
    keyword list conditions it just as well without reading like speech."""
    lowered = _COMMAND_PROMPT.lower()
    for phrase in ("i am ", "i say", "i start", "i interrupt", "my voice assistant"):
        assert phrase not in lowered, f"{phrase!r} is back in the prompt"


def test_the_prompt_still_primes_the_wake_word():
    """Removing the prose must not lose the fix it was added for: without
    "Onyx" in the prompt the decoder fused it into the next word
    ("Onyx, who is" -> "I am the CEO")."""
    assert "onyx" in _COMMAND_PROMPT.lower()
