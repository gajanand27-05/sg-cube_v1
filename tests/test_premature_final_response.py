"""A planner answer that arrives WITH its own tool calls is not an answer.

Observed live, reading a Notepad window:

    [ai] I've read the text from the Notepad window. Here's what it says:
         [The OCR result will be provided after the tool runs.]

The model emitted final_response AND tool_calls in one envelope. Commander
checked for "final_response" first, spoke it, and returned — so ocr_screen
never ran and the user was read a placeholder describing the answer it was
about to not get.

This is worse than an error. An error is visible; this is a fluent, confident
sentence with nothing behind it, and the user has no way to tell the
difference. The planner prompt already tries to suppress the behaviour
("Do NOT emit final_response until render_canvas has actually been called"),
which is evidence models do it anyway — so the commander must not trust it.

Rule: if the envelope carries tool calls, the tool calls win. The spoken
answer is produced on the next iteration, with real results in history.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.commander import _pending_tool_calls

OCR_CALL = {"name": "ocr_screen", "args": {}, "confidence": 0.9}


def test_the_reported_envelope_yields_its_tool_calls():
    """The exact shape from the Notepad screenshot."""
    content = {
        "final_response": "I've read the text from the Notepad window. "
                          "Here's what it says:\n\n"
                          "[The OCR result will be provided after the tool runs.]",
        "tool_calls": [OCR_CALL],
    }
    assert _pending_tool_calls(content) == [OCR_CALL], (
        "the placeholder answer would be spoken and the OCR skipped")


def test_a_genuine_answer_has_no_calls():
    """The normal path must stay untouched — this is how every spoken answer
    reaches the user."""
    assert _pending_tool_calls({"final_response": "Jensen Huang."}) == []


def test_an_empty_tool_calls_list_is_still_an_answer():
    """`{"final_response": ..., "tool_calls": []}` is a real answer. Treating
    an empty list as 'has calls' would mute the assistant entirely."""
    assert _pending_tool_calls({"final_response": "Done.", "tool_calls": []}) == []


def test_a_bare_calls_list_is_passed_through():
    assert _pending_tool_calls([OCR_CALL]) == [OCR_CALL]


def test_the_camelCase_spelling_is_honoured():
    """planner.py accepts toolCalls as well as tool_calls; if this helper only
    knew one spelling, the other would slip past as a spoken placeholder."""
    assert _pending_tool_calls({"final_response": "x", "toolCalls": [OCR_CALL]}) == [OCR_CALL]


def test_malformed_shapes_do_not_raise():
    """This runs on model output, so it must never be the thing that crashes
    a turn."""
    for junk in [None, "text", 42, {"tool_calls": "not-a-list"}, {}]:
        assert _pending_tool_calls(junk) == []
