"""What Onyx SAYS has to carry what the tool actually knew.

A tool can now report 'I did this but could not confirm it'. If the speech
layer flattens that back into a plain claim, the tool-layer honesty buys
nothing -- the user still hears a confident sentence with no evidence behind
it.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.runtime import _UNCONFIRMED_CONFIDENCE


def _record(name, message, confidence, status="success"):
    return {
        "name": name,
        "result": {
            "status": status,
            "message": message,
            "confidence": confidence,
            "confidence_reason": [],
        },
    }


def test_confirmed_result_is_spoken_plainly():
    from backend.core.brain import summarize_outcome
    spoken = summarize_outcome([_record("set_volume", "volume set to 50%", 100.0)])
    assert spoken == "volume set to 50%"


def test_unconfirmed_result_is_hedged():
    from backend.core.brain import summarize_outcome
    spoken = summarize_outcome(
        [_record("open_app", "opened notepad", _UNCONFIRMED_CONFIDENCE)]
    )
    assert spoken != "opened notepad", "unconfirmed result spoken as a plain claim"
    assert "couldn't confirm" in spoken.lower() or "could not confirm" in spoken.lower()
    assert "opened notepad" in spoken, "the hedge should still say what was attempted"


def test_confirmed_summary_hedges_unconfirmed_too():
    """The confirmation path is the costliest place to lie: the user
    explicitly authorised this action and is waiting to hear it happened."""
    from backend.core.agents.commander import _confirmed_summary

    batch = [{
        "name": "close_app",
        "result": {
            "status": "success",
            "message": "closed chrome",
            "confidence": _UNCONFIRMED_CONFIDENCE,
            "confidence_reason": [],
        },
    }]
    spoken = _confirmed_summary(batch, "close chrome")
    assert "couldn't confirm" in spoken.lower() or "could not confirm" in spoken.lower()


def test_confirmed_summary_leaves_confirmed_alone():
    from backend.core.agents.commander import _confirmed_summary

    batch = [{
        "name": "close_app",
        "result": {
            "status": "success",
            "message": "closed chrome",
            "confidence": 100.0,
            "confidence_reason": [],
        },
    }]
    assert _confirmed_summary(batch, "close chrome") == "closed chrome"


def test_planner_prompt_tells_the_model_what_confidence_means():
    """The tool_results handback already carries confidence via
    operator.py's res.model_dump(). If the prompt never explains it, the model
    narrates confidently regardless and iteration 2 launders the uncertainty
    away.

    Asserted against the prompt PlannerAgent actually builds, not against
    DEFAULT_PROMPTS: the live planner assembles its system prompt inline in
    _build_prompt and never reads the registry, so the same paragraph sitting
    in the registry alone would be dead text that no model ever sees.
    """
    from backend.core.agents.planner import PlannerAgent
    from backend.core.context.types import AgentContext

    prompt = PlannerAgent()._build_prompt(AgentContext(user_intent="turn the volume down"))
    # The prompt is hard-wrapped; compare on normalised whitespace so a rewrap
    # is not a test failure while a deletion still is.
    lowered = " ".join(prompt.lower().split())

    # Distinctive enough to fail if the guidance is removed OR reversed.
    assert "reduced confidence means the tool did the thing but could not confirm it" in lowered
    assert "never describe such a result as confirmed, completed or done" in lowered
    assert "contradicted" in lowered
    # The JSON envelope's own braces must survive the f-string intact.
    assert '{"tool_calls":' in prompt


def test_planner_prompt_is_not_only_in_the_registry():
    """Guard against the paragraph drifting back to being registry-only."""
    from backend.core.agents.planner import PlannerAgent
    from backend.core.context.types import AgentContext

    built = PlannerAgent()._build_prompt(AgentContext(user_intent="hi"))
    assert "confidence_reason" in built


def test_single_tool_fast_path_hedges_unconfirmed():
    """Commander's dominant spoken branch: one tool, success, has a message.
    ~105 tools declare no post-condition, so this path decides whether the
    honesty survives to the speaker at all."""
    from backend.core.brain import _hedge

    unconfirmed = {
        "status": "success",
        "message": "opened notepad",
        "confidence": _UNCONFIRMED_CONFIDENCE,
        "confidence_reason": [],
    }
    spoken = _hedge(str(unconfirmed["message"]), unconfirmed)
    assert "couldn't confirm" in spoken.lower()

    confirmed = dict(unconfirmed, confidence=100.0)
    assert _hedge(str(confirmed["message"]), confirmed) == "opened notepad"


def test_commander_single_tool_branch_calls_hedge():
    """The above proves _hedge works; this proves the branch USES it."""
    import inspect
    from backend.core.agents import commander as commander_mod

    src = inspect.getsource(commander_mod.CommanderAgent._run_loop_stream)
    assert 'spoken = _hedge(str(msg), res)' in src, (
        "the single-tool fast path speaks the tool's claim verbatim again"
    )


def test_contradicted_result_speaks_its_reason():
    """A contradicted post-condition's reason -- 'volume is 30%, expected 50%'
    -- is the most informative sentence this feature produces. It used to be
    dropped for the literal word 'that'."""
    from backend.core.agents.commander import _confirmed_summary

    batch = [{
        "name": "set_volume",
        "result": {
            "status": "error",
            "message": None,
            "reason": "volume is 30%, expected 50%",
            "confidence": 0.0,
            "confidence_reason": ["contradicted: volume is 30%, expected 50%"],
        },
    }]
    spoken = _confirmed_summary(batch, "set volume")
    assert "volume is 30%, expected 50%" in spoken
    assert "that" != spoken.rsplit(": ", 1)[-1]


def test_failure_with_no_message_or_reason_names_the_tool():
    """The wrapper key is 'name' (operator.execute_batch), never 'tool'."""
    from backend.core.agents.commander import _confirmed_summary

    batch = [{"name": "set_volume", "result": {"status": "error"}}]
    assert "set_volume" in _confirmed_summary(batch, "set volume")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
