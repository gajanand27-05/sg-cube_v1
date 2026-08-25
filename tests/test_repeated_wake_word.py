"""T-repeated-wake-word-opens-an-app.

The wake word repeated is still someone calling for attention, but only the
first one is stripped (deliberately — "what is onyx 130" is a question about
onyx). What is left is a sentence made entirely of the assistant's name, and
the planner read it as a request to launch something called Onyx:

    [command] 'Onyx, onyx, onyx, onyx.'
    [trigger] stripped wake prefix: 'Onyx, onyx, onyx, onyx.' -> 'onyx, onyx, onyx.'
    [ai] response: I attempted to open the Onyx application, but the task was
                   cancelled, so it was not opened. (tools: 1)
    The system cannot find the file Onyx.

A bare "Onyx" already behaves correctly — it reaches the planner as an
attention call and gets answered conversationally. So the repeated form
should collapse to exactly that, not turn into a command.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.orchestrator.normalize import strip_wake_prefix


def test_repeated_wake_word_collapses_to_a_bare_attention_call():
    for text in [
        "Onyx, onyx, onyx, onyx.",
        "onyx onyx",
        "Onyx. Onyx.",
        "Onyx, onyx!",
        "hey onyx, onyx",
    ]:
        out = strip_wake_prefix(text)
        assert out.strip().lower().rstrip(".!?,") == "onyx", (
            f"{text!r} -> {out!r}; a pile of wake words is still just the wake word"
        )


def test_bare_wake_word_is_unchanged():
    """The existing contract: don't strip it to nothing, the gate needs it."""
    assert strip_wake_prefix("Onyx").strip().lower() == "onyx"
    assert strip_wake_prefix("Onyx.").strip().lower().rstrip(".") == "onyx"


def test_real_commands_still_lose_exactly_one_prefix():
    assert strip_wake_prefix("Onyx, close chrome.") == "close chrome."
    assert strip_wake_prefix("Onyx, open whatsapp") == "open whatsapp"
    assert strip_wake_prefix("hey onyx, what time is it?") == "what time is it?"
    # Only the FRONT: a question about onyx keeps its subject.
    assert strip_wake_prefix("what is onyx 130") == "what is onyx 130"


def test_command_after_repeated_wake_words_survives():
    """Repetition is a stutter, not a reason to lose the command behind it."""
    assert strip_wake_prefix("Onyx, onyx, open notepad") == "open notepad"
    assert strip_wake_prefix("onyx onyx onyx close chrome") == "close chrome"
