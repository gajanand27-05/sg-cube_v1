"""T-one-utterance-opened-six-apps.

    [command] 'Notepad, chrome, firefox, vscode, spotify, whatsapp, read the news, set a reminder,'
    ... opened Notepad ... opened Google Chrome ... opened Firefox ESR ...
    ... opened vscode ... opened spotify ... opened WhatsApp ... (tools: 7)

Six applications launched and a news fetch, from one utterance, with no
confirmation. Note the trailing comma: the capture cut the user off
mid-sentence, and what they were doing was reading a list aloud.

Nothing here is a permission-policy violation. `open_app` is SYSTEM_WRITE and
trusted on purpose — prompting before opening a single app would make a voice
assistant useless, and that decision stands. The missing guard is on the
FAN-OUT: one utterance turning into an unbounded number of side-effecting
actions is a different event from one utterance asking for one action, and
its most likely cause is a misheard or run-on transcript.

Readonly calls are not counted. Fetching five things to answer a question is
research, not consequence.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.guardian import GuardianAgent, MAX_UNCONFIRMED_SIDE_EFFECTS


class _Verdict:
    """A verifier that waves everything through, so the brake is what's tested."""
    is_valid = True
    needs_confirmation = False
    is_critical = False
    error = ""
    reasoning = ""


def _plan(*names) -> list[dict]:
    return [{"name": n, "args": {"name": n}} for n in names]


def _verify(calls):
    async def _stub(*_a, **_kw):
        return _Verdict()

    with patch("backend.core.agents.guardian.verify_call", side_effect=_stub):
        return asyncio.run(
            GuardianAgent().verify_plan("some utterance", calls, "req-1", None)
        )


def test_six_apps_from_one_utterance_needs_confirmation():
    valid, pending, errors = _verify(
        _plan("open_app", "open_app", "open_app", "open_app", "open_app",
              "open_app", "get_news_data")
    )

    assert not errors
    assert len(pending) == 6, (
        f"only {len(pending)} of 6 app launches were gated: this is the turn "
        "that opened Notepad, Chrome, Firefox, vscode, spotify and WhatsApp"
    )
    assert all(c.get("needs_confirmation") for c in pending)
    assert not any(c["name"] == "open_app" for c in valid)


def test_an_ordinary_two_step_plan_still_runs_unprompted():
    """Do not turn every compound request into an interrogation."""
    valid, pending, errors = _verify(_plan("open_app", "play_youtube"))

    assert not errors
    assert pending == []
    assert len(valid) == 2


def test_a_single_action_still_runs_unprompted():
    valid, pending, errors = _verify(_plan("open_app"))
    assert (len(valid), pending) == (1, [])


def test_readonly_fan_out_is_not_gated():
    """Five lookups to answer one question is research, not consequence."""
    valid, pending, errors = _verify(
        _plan("get_time", "get_battery", "get_system_status", "get_news_data",
              "web_search", "get_time")
    )
    assert pending == []
    assert len(valid) == 6


def test_unknown_tools_count_as_side_effecting():
    """A name the registry cannot resolve fails safe, like the tier default."""
    valid, pending, errors = _verify(
        _plan("frobnicate", "frobnicate", "frobnicate")
    )
    assert len(pending) == 3


def test_the_threshold_is_the_documented_one():
    """Guard the boundary so it cannot drift silently."""
    n = MAX_UNCONFIRMED_SIDE_EFFECTS
    at_limit = _verify(_plan(*(["open_app"] * n)))
    assert at_limit[1] == [], f"{n} side effects should not prompt"

    over = _verify(_plan(*(["open_app"] * (n + 1))))
    assert len(over[1]) == n + 1, f"{n + 1} side effects should prompt"


def test_the_prompt_says_what_and_how_many():
    """"permission to open app" for six launches hides the scale."""
    from backend.core.agents.commander import _fan_out_summary

    calls = [
        {"name": "open_app", "args": {"name": "Notepad"}},
        {"name": "open_app", "args": {"name": "Chrome"}},
        {"name": "open_app", "args": {"name": "Firefox"}},
        {"name": "open_app", "args": {"name": "vscode"}},
        {"name": "open_app", "args": {"name": "spotify"}},
        {"name": "open_app", "args": {"name": "WhatsApp"}},
    ]
    summary = _fan_out_summary(calls)

    assert "Notepad" in summary and "Chrome" in summary
    assert "2 more" in summary, summary
    # The app names are the point — six identical tool names say nothing.
    assert summary.count("open app") == 4, summary


def test_fan_out_summary_handles_a_short_list():
    from backend.core.agents.commander import _fan_out_summary

    out = _fan_out_summary([
        {"name": "open_app", "args": {"name": "Chrome"}},
        {"name": "play_youtube", "args": {"query": "lofi"}},
    ])
    assert out == "open app Chrome and play youtube lofi", out


def test_open_app_really_is_side_effecting_in_the_live_registry():
    """The brake is only as good as the tier lookup behind it."""
    from backend.core.agents.guardian import _has_side_effects

    import backend.core.tools.builtins  # noqa: F401 - populates REGISTRY

    assert _has_side_effects({"name": "open_app"}) is True
    assert _has_side_effects({"name": "get_time"}) is False
