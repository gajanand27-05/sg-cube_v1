"""An empty result must not be announced as success.

Repeatedly, live:

    [command] 'Open code is there.'
    [ai] response: Done.  (latency: 959ms, tools: 0)

    [command] 'I am going to take a tablet and drink some water.'
    [ai] response: Done.  (latency: 920ms, tools: 0)

Nothing was opened and nothing was done. "Done." was not the planner
hallucinating — brain.py substituted the literal string whenever the stream
ended with an empty sentence buffer:

    spoken_text=sentence_buffer.strip() if sentence_buffer else "Done."

That is the assistant fabricating a success claim out of no result at all. It
is the worst failure mode available to it: an error is visible and a silence
is obvious, but a confident "Done." is indistinguishable from having actually
worked, so the user only finds out by going to look.

Two honest replacements, depending on what really happened:
  * tools ran        -> say what they did, from their own messages
  * nothing ran      -> admit it, and never in the grammar of completion
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.brain import summarize_outcome


class _Res:
    """A ToolResult-shaped object (attributes, not keys)."""

    def __init__(self, status="success", message=""):
        self.status = status
        self.message = message


def test_nothing_ran_is_never_reported_as_done():
    """The reported case. Zero tools, no text — there is nothing to claim."""
    spoken = summarize_outcome([])
    assert "done" not in spoken.lower(), f"still claims completion: {spoken!r}"
    assert spoken.strip(), "an empty string would make it silently do nothing"


def test_nothing_ran_does_not_use_the_grammar_of_success():
    """"Finished", "all set", "taken care of" are the same lie in a different
    costume. The reply has to read as an admission."""
    spoken = summarize_outcome([]).lower()
    for claim in ("done", "finished", "completed", "all set", "taken care of"):
        assert claim not in spoken, f"{claim!r} in {spoken!r}"


def test_a_successful_tool_is_described_by_its_own_message():
    """The tool already said something true and specific. "Opened Notepad"
    beats any sentence we could invent."""
    spoken = summarize_outcome([{"name": "open_app",
                                 "result": _Res("success", "opened Notepad")}])
    assert "opened Notepad" in spoken


def test_several_tools_are_all_reported():
    spoken = summarize_outcome([
        {"name": "open_app", "result": _Res("success", "opened Notepad")},
        {"name": "set_volume", "result": _Res("success", "volume set to 50")},
    ])
    assert "opened Notepad" in spoken and "volume set to 50" in spoken


def test_a_failed_tool_is_not_reported_as_success():
    """A tool that ran and failed is the case most likely to be papered
    over — it has a record, so a naive summary counts it as activity."""
    spoken = summarize_outcome([
        {"name": "open_app", "result": _Res("error", "")},
    ]).lower()
    assert "done" not in spoken
    for claim in ("opened", "finished", "completed"):
        assert claim not in spoken, f"{claim!r} in {spoken!r}"


def test_a_mix_reports_only_what_succeeded():
    spoken = summarize_outcome([
        {"name": "open_app", "result": _Res("success", "opened Notepad")},
        {"name": "send_email", "result": _Res("error", "")},
    ])
    assert "opened Notepad" in spoken


def test_dict_shaped_results_are_handled():
    """Tool results arrive as ToolResult objects in some paths and plain
    dicts in others; a shape mismatch here would silently summarise nothing
    and fall back to the admission."""
    spoken = summarize_outcome([
        {"name": "open_app", "result": {"status": "success",
                                        "message": "opened Notepad"}},
    ])
    assert "opened Notepad" in spoken


def test_malformed_records_never_raise():
    """This runs at the end of every turn, including the failed ones."""
    for junk in ([None], [{}], [{"result": None}], ["nonsense"], None):
        assert summarize_outcome(junk).strip()


def test_a_successful_tool_with_no_message_still_says_something_true():
    """Some tools return success with an empty message. Naming the tool is
    honest; inventing an outcome is not."""
    spoken = summarize_outcome([{"name": "lock_screen",
                                 "result": _Res("success", "")}])
    assert "lock" in spoken.lower()
