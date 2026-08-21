"""The planner had no clock, so it guessed the time of day from the words.

Live, in the evening:

    [command] 'Onyx morning.'
    [ai] response: Good morning! How can I help you today?  (tools: 0)

It was not reading a clock and getting it wrong — there was no clock to read.
Nothing in _build_prompt ever mentioned the date or time, so the model
mirrored "morning" straight back out of the transcript.

get_time exists as a tool, but a tool call cannot fix this: the model has to
already suspect the time matters before it will call one, and "good morning"
never feels like it needs a lookup. The date belongs in the prompt, where it
is free and always right.
"""
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.planner import PlannerAgent


def _prompt() -> str:
    """The real AgentContext — a SimpleNamespace stub silently lacks fields
    _build_prompt reads, and would fail for the wrong reason."""
    from backend.core.context.types import AgentContext

    return PlannerAgent()._build_prompt(AgentContext(user_intent="hello"))


def test_the_prompt_states_the_current_date_and_time():
    now = datetime.now()
    prompt = _prompt()
    assert str(now.year) in prompt, "no year in the planner prompt"
    assert now.strftime("%A") in prompt, "no weekday in the planner prompt"
    assert re.search(r"\d{1,2}:\d{2}", prompt), "no clock time in the planner prompt"


def test_the_time_is_local_not_utc():
    """A UTC clock in an IST room is a wrong clock, not a missing one — and
    wrong is worse, because it reads as authoritative."""
    prompt = _prompt()
    assert datetime.now().strftime("%H:%M")[:2] in prompt or \
        datetime.now().strftime("%I:%M").lstrip("0")[:2] in prompt, \
        "the hour in the prompt does not match local time"


def test_the_prompt_tells_the_model_to_use_it():
    """Stating the time is not enough — the model has to know it may rely on
    it instead of guessing or calling get_time for a greeting."""
    prompt = _prompt().lower()
    assert "do not guess" in prompt or "without calling" in prompt, \
        "nothing tells the planner it can trust the stated time"
