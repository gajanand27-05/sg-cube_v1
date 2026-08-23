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
    away."""
    from backend.core.prompts.registry import DEFAULT_PROMPTS
    planner = DEFAULT_PROMPTS["planner"]["content"].lower()
    assert "confidence" in planner
    assert "confirm" in planner


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
