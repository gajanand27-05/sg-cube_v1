"""Whisper must be primed for the proper nouns this user actually says.

Measured failures, all live:

    "Nikola Tesla"  -> 'Nicoletta', 'Nicola Tere'
    "Gajanand"      -> 'Gajanan'      (twice in one utterance, and the
                                       misheard spelling was then written to
                                       permanent memory by remember())
    "Sharath"       -> 'sharat'       (in a WhatsApp recipient)

Same defect the wake word already had and that this prompt already fixes:
an unprimed proper noun has no context, so the decoder rewrites it into
whatever common words are nearby. The comment above _COMMAND_PROMPT records
"Onyx, who is the CEO of Nvidia" decoding as 'I am the CEO of Nvia.' until
the name was primed. Names the user says every day deserve the same.

Two constraints this must not break:

  * KEYWORDS, NOT SENTENCES. An earlier prompt opened with "I am talking to
    my voice assistant, which is called Onyx." and Whisper handed it back
    verbatim as a transcript. A name list conditions the decoder just as well
    and does not read like something a person said.
  * Priming a name the user SAYS means their real commands now overlap the
    prompt. is_prompt_echo() must still not swallow them — that failure is
    silent and far worse than the echo it guards, because working speech
    vanishes with no error anywhere.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech.stt_whisper import (
    _COMMAND_PROMPT, _PROMPT_ECHO_MIN_WORDS, is_prompt_echo,
)
from backend.daemon.trigger import _is_dispatchable

PRIMED_NAMES = ["Gajanand", "Sharath", "Nikola Tesla", "Onyx"]


@pytest.mark.parametrize("name", PRIMED_NAMES)
def test_the_name_is_primed(name):
    assert name.lower() in _COMMAND_PROMPT.lower(), (
        f"{name!r} is not in the decoder prompt, so it has no context and "
        "gets rewritten into whatever common words sound nearby"
    )


def test_the_prompt_stays_keyword_shaped():
    """Prose is what Whisper emits verbatim when the audio gives it nothing.

    The first draft's opening sentence came back AS A TRANSCRIPT when a
    Kannada utterance was force-decoded as English. Adding names must not
    reintroduce anything that reads like a person talking.
    """
    low = _COMMAND_PROMPT.lower()
    for tell in ("i am ", "i'm ", "my name is", "which is called",
                 "i am talking", "you are", "please "):
        assert tell not in low, (
            f"{tell!r} makes the prompt read like speech; Whisper will hand "
            "it back as a transcript when the audio does not decode"
        )


# ── the guard that must not over-fire ──────────────────────────────────


@pytest.mark.parametrize("command", [
    "information about Nikola Tesla",
    "tell me about nikola tesla",
    "who was nikola tesla and what did he invent",
    "send a whatsapp message to Sharath",
    "send sharath a message saying hi how are you doing",
    "my name is Gajanand not Gajanand2",
    "onyx what is the weather",
])
def test_a_real_command_using_a_primed_name_is_not_eaten(command):
    """The dangerous direction.

    Priming a name the user SAYS means their genuine commands now share words
    with the prompt. If is_prompt_echo starts matching them, the command is
    replaced by "" and the content gate drops it — the user is simply never
    heard, with nothing in any log saying why.
    """
    assert not is_prompt_echo(command), (
        f"{command!r} was classified as the decoder reciting its own prompt"
    )
    assert _is_dispatchable(command), f"{command!r} would be dropped"


def test_a_verbatim_recital_is_still_caught():
    """The guard still has to work. A long run of the prompt read back is
    the thing it exists for."""
    words = _COMMAND_PROMPT.split()
    run = " ".join(words[:_PROMPT_ECHO_MIN_WORDS + 6])
    assert is_prompt_echo(run), (
        f"a {len(run.split())}-word verbatim run of the prompt was not "
        "recognised as an echo; it would be dispatched as a command"
    )


def test_the_name_block_alone_is_too_short_to_trip_the_guard():
    """Names are short. Even if the decoder emits only the name list, that
    is under the word floor, so it cannot be mistaken for a recital — it
    falls through to the ordinary content gate instead."""
    assert len("Gajanand Sharath Nikola Tesla".split()) < _PROMPT_ECHO_MIN_WORDS


# ── wiring ─────────────────────────────────────────────────────────────


def test_both_transcribe_paths_use_the_prompt():
    """The GPU path and the offline CPU path must be primed identically, or
    a name works until the network drops and then quietly stops working."""
    import inspect

    from backend.ai_modules.speech import stt_whisper

    for fn in (stt_whisper.transcribe_array, stt_whisper.transcribe_array_cpu):
        src = inspect.getsource(fn)
        assert "initial_prompt=_COMMAND_PROMPT" in src, (
            f"{fn.__name__} does not pass the prompt"
        )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
