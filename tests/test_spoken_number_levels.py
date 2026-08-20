"""Spelled-out numbers must set levels, not fall through to the planner.

Found by tools/stt_bench.py against a real recorded corpus: "set volume to
fifty" did not match any rule, while "set volume to 50" did. Whisper happens
to emit digits for this phrasing, which hid the gap — but that is a property
of the decoder's formatting, not a guarantee. Change the initial_prompt, the
model, or the phrasing ("set volume to a hundred") and the spelled form
reaches the router, matches nothing, and a deterministic 0.1ms rule becomes a
multi-second planner round-trip that may not even call set_volume.

Levels only. Spelled arithmetic ("what is fifteen times four") is out of
scope: it needs word-expression parsing, not a token lookup.
"""
import pytest

from backend.core.orchestrator.normalize import normalize_for_rules
from backend.core.orchestrator.rule_engine import match

# (input, expected action, expected level)
CASES = [
    ("set volume to fifty", "set_volume", 50),
    ("set volume to twenty", "set_volume", 20),
    ("set volume to a hundred", "set_volume", 100),
    ("set volume to one hundred", "set_volume", 100),
    ("volume fifty", "set_volume", 50),
    ("set volume to seventy five percent", "set_volume", 75),
    ("change volume to thirty", "set_volume", 30),
    ("set volume to zero", "set_volume", 0),
    ("set brightness to forty", "set_brightness", 40),
    ("brightness sixty", "set_brightness", 60),
    ("set brightness to eighty percent", "set_brightness", 80),
]


@pytest.mark.parametrize("text,action,level", CASES)
def test_spelled_level_matches_rule(text, action, level):
    intent = match(normalize_for_rules(text))
    assert intent is not None, f"{text!r} fell through to the planner"
    assert intent.action == action
    assert intent.args.get("level") == level


@pytest.mark.parametrize("text,action,level", CASES)
def test_digit_form_still_matches(text, action, level):
    """The digit path is what production actually receives today — adding the
    spelled alternation must not regress it."""
    digits = text.replace("seventy five", "75").replace("one hundred", "100")
    for word, num in [("a hundred", "100"), ("fifty", "50"), ("twenty", "20"),
                      ("thirty", "30"), ("forty", "40"), ("sixty", "60"),
                      ("eighty", "80"), ("zero", "0")]:
        digits = digits.replace(word, num)
    intent = match(normalize_for_rules(digits))
    assert intent is not None, f"{digits!r} fell through to the planner"
    assert intent.action == action
    assert intent.args.get("level") == level


def test_out_of_range_spelled_level_does_not_match():
    """Guard the alternation against absurd values the digit rule also rejects
    (\\d{1,3} caps at 999)."""
    assert match(normalize_for_rules("set volume to one thousand")) is None


def test_number_word_inside_a_target_is_not_rewritten():
    """The conversion must be scoped to level rules. A global word->digit pass
    would corrupt free-text targets like this one."""
    intent = match(normalize_for_rules("play one more time on youtube"))
    if intent is not None and intent.target:
        assert "one more time" in intent.target, (
            f"target was rewritten to {intent.target!r}")
