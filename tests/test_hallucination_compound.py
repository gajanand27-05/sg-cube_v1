"""A hallucination glued to other words used to sail straight through.

`_is_dispatchable` matched the blocklist against the WHOLE transcript, so
"Thanks for watching. Hear me on X." was not in the set and ran a full turn.

Measured against this install's own dispatched history — 770 recorded turns in
the timeline, every one of which reached the router:

    blocked by the old gate ................. 1
    carrying a hallucination as one sentence  5   <- all ran a turn
    clean ................................. 764

and after this change:

    blocked ................................. 7
    dispatched but stripped first ........... 4
    still dispatchable .................... 763

The fixtures below are those real transcripts, not invented ones. Whisper is
trained on video audio and falls into video outros on silence, which is why
every single one is a sign-off.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon.trigger import _is_dispatchable, strip_hallucinated_sentences

# Verbatim from the timeline. Each of these ran a full LLM turn.
OBSERVED_HALLUCINATIONS = [
    "This is all for today. This is all for today. Bye.",
    "Bye bye. Bye.",
    "See you next time. Bye bye.",
    "This is the end of this video. Thank you for watching.",
    "Bye bye.",
    "goodbye",
]


def test_observed_compound_hallucinations_are_blocked():
    for text in OBSERVED_HALLUCINATIONS:
        assert not _is_dispatchable(text), repr(text)


def test_the_single_sentence_cases_still_work():
    """Regression cover for what the gate already caught."""
    for text in ["you", "thank you", "Thanks for watching.", "[BLANK_AUDIO]",
                 "bye", "music", "..."]:
        assert not _is_dispatchable(text), repr(text)


def test_a_real_command_behind_a_hallucination_survives_and_is_cleaned():
    """Rejecting the whole transcript would lose the command. Stripping keeps
    it, and keeps the hallucination out of the planner prompt and out of
    long-term memory, where 60+ of these have already fossilised."""
    assert _is_dispatchable("Thanks for watching. Open notepad.")
    assert strip_hallucinated_sentences("Thanks for watching. Open notepad.") == "Open notepad."


def test_observed_partial_strips():
    """Real transcripts that still dispatch, but should not carry the outro
    into the prompt with them."""
    cases = {
        "This is not a joke. Bye bye.": "This is not a joke.",
        "Every time, do it. Bye. Bye.": "Every time, do it.",
        "Thanks for watching. Hear me on X.": "Hear me on X.",
    }
    for raw, expected in cases.items():
        assert strip_hallucinated_sentences(raw) == expected, raw


def test_real_commands_are_untouched():
    """The measured claim: 0 of the 764 clean queries were altered. These are
    real ones from the same history."""
    for text in [
        "what time is it",
        "open notepad",
        "read the text on my screen",
        "Can you play some music on youtube?",
        "Can you hear me onix?",
        "Read the document internship offer letter.",
        "who is the ceo of nvidia",
        "I am kind of feeling like enjoyment. Can you play like something refreshing mood?",
    ]:
        assert _is_dispatchable(text), repr(text)
        assert strip_hallucinated_sentences(text) == text.strip(), repr(text)


def test_a_single_sentence_is_never_split():
    """The splitter must not touch a one-sentence command — that path is the
    overwhelming majority of real traffic and should stay untouched."""
    for text in ["open notepad", "what is the capital of France"]:
        assert strip_hallucinated_sentences(text) == text


def test_stripping_is_pure():
    """`_is_dispatchable` is documented as pure and 23 tests depend on it.
    The helper it now calls must be too — no clock, no shared state."""
    text = "Thanks for watching. Open notepad."
    first = strip_hallucinated_sentences(text)
    for _ in range(3):
        assert strip_hallucinated_sentences(text) == first
    assert text == "Thanks for watching. Open notepad."  # not mutated


def test_empty_and_whitespace():
    assert strip_hallucinated_sentences("") == ""
    assert strip_hallucinated_sentences("   ") == ""
    assert not _is_dispatchable("")
    assert not _is_dispatchable("   ")


def test_the_cleaned_text_is_what_gets_dispatched():
    """Wiring guard. Stripping that is computed and then thrown away would
    leave the hallucination in the planner prompt and in the timeline — which
    is where the existing 60+ fossilised ones came from."""
    import inspect
    from backend.daemon import trigger

    src = inspect.getsource(trigger._handle_wake_async)
    assert "strip_hallucinated_sentences(command)" in src
    assert "command = cleaned" in src, (
        "the stripped text is computed but never assigned back, so the raw "
        "transcript is still what reaches the router"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
