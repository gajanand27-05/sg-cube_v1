"""Regression corpus for the router's rule tier — see T-rule-tier-overmatch.

The rule tier used to intercept natural-language questions and mangle the
inputs it did match, because (a) the cache-key normalizer stripped the
operators and dots that rules match on, and (b) greedy `.+` patterns were
reachable for any input via a fallback linear scan.

Mis-matches here are worse than errors: a failure is visible, but
calculate("the capital of france") returns a confident wrong answer.

Every case asserts the action AND the target — a rule that fires with a
mangled target is still a bug. LLM means match() must return None so the
query falls through to the planner.
"""
import pytest

from backend.core.orchestrator.normalize import normalize, normalize_for_rules
from backend.core.orchestrator.rule_engine import match

LLM = None

# (raw user input, expected action or LLM, expected target or None to skip)
CASES: list[tuple[str, str | None, str | None]] = [
    # ── Arithmetic must reach the calculator with the expression INTACT ──
    # Regression: normalize() stripped the operators, so "calculate 2+2"
    # arrived as calculate("22") and returned 22.
    ("calculate 2+2", "calculate", "2+2"),
    ("what is 15 * 3", "calculate", "15 * 3"),
    ("what is 100 / 4", "calculate", "100 / 4"),
    ("calculate 12 - 4", "calculate", "12 - 4"),
    ("what is 20 percent of 50", "calculate", "20 percent of 50"),

    # ── URLs must reach open_url INTACT ──
    # Regression: both URL rules require a literal ".", which normalize()
    # always removed, making them unreachable dead code.
    ("open github.com", "open_url", "github.com"),
    ("go to https://news.ycombinator.com", "open_url", "https://news.ycombinator.com"),
    ("open localhost:3000", "open_url", "localhost:3000"),

    # ── Natural questions must fall through to the LLM ──
    ("what is the capital of France", LLM, None),
    ("what is machine learning", LLM, None),
    ("why is the sky blue", LLM, None),
    ("summarize the plot of hamlet", LLM, None),
    ("how do I center a div", LLM, None),
    ("what is your opinion on jazz music", LLM, None),
    ("what is a black hole", LLM, None),
    ("start working on the report", LLM, None),

    # ── Legitimate rule hits must STILL work ──
    ("open notepad", "open_app", "notepad"),
    ("open chrome", "open_app", "chrome"),
    ("close chrome", "close_app", "chrome"),
    ("what time is it", "get_time", ""),
    ("volume up", "volume_up", ""),
    ("set volume to 50 percent", "set_volume", ""),
    ("take a screenshot", "screenshot", ""),
    ("mute", "mute", ""),
    ("what is the weather", "get_weather", ""),
    ("what's the weather in Tokyo", "get_weather", "tokyo"),

    # ── The reminder distinction: an instruction vs a question ──
    ("remind me to call mom", "set_reminder", "call mom"),
    ("remind me why we chose Postgres", LLM, None),

    # ── summarize only fires on an actual document ──
    ("summarize report.pdf", "summarize_pdf", "report.pdf"),
    ("summarize https://example.com/post", "summarize_url", "https://example.com/post"),
]


@pytest.mark.parametrize("raw,expected_action,expected_target", CASES)
def test_rule_tier_routing(raw, expected_action, expected_target):
    intent = match(normalize_for_rules(raw))

    if expected_action is LLM:
        assert intent is None, (
            f"{raw!r} must fall through to the LLM, but the rule tier "
            f"claimed it as {intent.action}({intent.target!r})"
        )
        return

    assert intent is not None, f"{raw!r} should match {expected_action}, got None"
    assert intent.action == expected_action, (
        f"{raw!r}: expected {expected_action}, got {intent.action}"
    )
    if expected_target is not None:
        assert intent.target == expected_target, (
            f"{raw!r}: target mangled — expected {expected_target!r}, "
            f"got {intent.target!r}"
        )


def test_normalize_for_rules_preserves_matchable_characters():
    """The whole point of the second normalizer: operators and dots survive."""
    assert normalize_for_rules("Calculate 2+2.") == "calculate 2+2"
    assert normalize_for_rules("Open GitHub.com") == "open github.com"
    assert normalize_for_rules("what is 15 * 3?") == "what is 15 * 3"
    assert normalize_for_rules('"take a screenshot"') == "take a screenshot"
    assert normalize_for_rules("  OPEN   notepad  ") == "open notepad"


def test_cache_key_normalizer_is_unchanged():
    """normalize() keeps its old punctuation-stripping behavior — cache
    entries and other callers depend on it."""
    assert normalize("Open Notepad.") == "open notepad"
    assert normalize("what time is it?") == "what time is it"
    assert normalize("  CLOSE  Chrome ") == "close chrome"
    assert normalize("calculate 2+2") == "calculate 22"


def test_url_rules_are_reachable():
    """Guards the exact dead-code condition: the URL rules require a literal
    dot, so feeding them normalize() output could never match them.

    The old path did not fail loudly — it fell through to open_app with the
    dot silently deleted, i.e. a confident wrong answer. That is the failure
    mode this whole ticket is about.
    """
    broken = match(normalize("open github.com"))
    assert broken is not None and broken.action == "open_app"
    assert broken.target == "githubcom", "the dot is eaten by normalize()"

    fixed = match(normalize_for_rules("open github.com"))
    assert fixed is not None and fixed.action == "open_url"
    assert fixed.target == "github.com"
