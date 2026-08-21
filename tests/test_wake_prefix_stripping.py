"""The wake word in the transcript bypasses every rule in the router.

Live:

    [command] 'Onyx, close chrome.'
    [ai] response: Done.  (latency: 1748ms, tools: 0)

Chrome stayed open. "Done." with zero tools is the most dishonest failure the
assistant has — it is indistinguishable from success.

The cause is not the planner. Every rule pattern is anchored with ^, and
nothing ever stripped the wake phrase, so:

    'close chrome'        -> close_app:'chrome'      (0.1ms, actually closes)
    'Onyx, close chrome.' -> no rule -> planner      (1748ms, says "Done.")

The wake word is IN the transcript because the capture starts with it (the
pre-roll deliberately includes it). Priming Whisper for the name made it
transcribe reliably as its own token instead of fusing into the next word —
which fixed the fusion and made this failure universal at the same time, for
every rule, on every wake-prefixed command.

Stripping happens next to strip_hallucinated_sentences: after the content
gate, before dispatch, so the rules, the cache key and the planner prompt all
see the same cleaned command.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.orchestrator.normalize import normalize_for_rules, strip_wake_prefix
from backend.core.orchestrator.rule_engine import match


@pytest.mark.parametrize("spoken, bare", [
    # Trailing punctuation is left alone — normalize_for_rules strips it, and
    # the planner reads better with the sentence intact.
    ("Onyx, close chrome.", "close chrome."),
    ("onyx close chrome", "close chrome"),
    ("Onyx. What time is it?", "What time is it?"),
    ("Onyx, open notepad", "open notepad"),
    ("ONYX  —  lock the screen", "lock the screen"),
    ("Hey Onyx, open chrome", "open chrome"),
    ("OK Onyx, set volume to fifty", "set volume to fifty"),
])
def test_the_wake_prefix_is_removed(spoken, bare):
    assert strip_wake_prefix(spoken) == bare


@pytest.mark.parametrize("spoken", [
    "Onyx, close chrome.",
    "Onyx. What time is it?",
    "onyx open notepad",
    "Onyx, lock the screen",
])
def test_wake_prefixed_commands_reach_their_rule(spoken):
    """The actual regression: these all fell through to the planner."""
    intent = match(normalize_for_rules(strip_wake_prefix(spoken)))
    assert intent is not None, f"{spoken!r} still misses every rule"


def test_the_bare_wake_word_is_left_alone():
    """"Onyx" on its own is not a command with the name removed — it is the
    user getting attention. Stripping it to "" would turn it into an empty
    transcript, and the content gate should be what rejects it."""
    assert strip_wake_prefix("Onyx") == "Onyx"
    assert strip_wake_prefix("Onyx.") == "Onyx."
    assert strip_wake_prefix("   onyx  ") == "   onyx  "


def test_the_name_is_only_stripped_from_the_FRONT():
    """"what is onyx 130" is a question ABOUT onyx. Removing the word
    anywhere it appears would silently rewrite the user's query."""
    assert strip_wake_prefix("what is onyx 130") == "what is onyx 130"
    assert strip_wake_prefix("search for onyx paint") == "search for onyx paint"


def test_only_one_leading_wake_word_is_removed():
    """Vosk partials like '[unk] [unk] onyx' show the word can land twice.
    Removing the first is enough; consuming an unbounded run risks eating a
    real word that follows."""
    assert strip_wake_prefix("onyx onyx close chrome") == "onyx close chrome"


def test_a_command_without_the_wake_word_is_untouched():
    """Follow-up turns carry no wake word at all and must pass through
    byte-identical."""
    for text in ["close chrome", "what time is it", "and the one after that"]:
        assert strip_wake_prefix(text) == text


def test_empty_and_none_are_safe():
    assert strip_wake_prefix("") == ""
    assert strip_wake_prefix(None) == ""
