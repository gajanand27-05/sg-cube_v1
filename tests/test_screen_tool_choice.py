"""Reading the screen must reach OCR, and the VLM must have a reachable budget.

Two findings from a live rehearsal, both invisible to the suite:

1. describe_screen runs a local vision model measured at 34-39s per image,
   against runtime.run_tool's 30s default. It could never return anything but
   "Execution timed out" — the tool was unreachable, not slow.

2. Asked to "read the text on my screen" the planner chose describe_screen on
   one run and ocr_screen on another. The descriptions did not make the split
   decidable: both claimed the screen, neither stated its cost.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import backend.core.tools  # noqa: F401  (populates REGISTRY)
from backend.core.tools.registry import REGISTRY, _timeout_for_tool
from backend.server.config import settings

# Measured on this hardware, 2026-08-14. If the model or machine changes this
# number should be re-measured, not nudged.
VLM_OBSERVED_MAX_S = 39.0


def test_the_vision_model_has_time_to_finish():
    budget = _timeout_for_tool(REGISTRY["describe_screen"])
    assert budget > VLM_OBSERVED_MAX_S, (
        f"describe_screen budget is {budget}s but the VLM was measured at up "
        f"to {VLM_OBSERVED_MAX_S}s — it can only ever time out"
    )


def test_ocr_is_not_stuck_behind_the_vision_budget():
    """OCR is ~3s; it should not be sharing a 60s LLM budget by accident."""
    assert _timeout_for_tool(REGISTRY["ocr_screen"]) <= settings.tool_timeout_default_s


@pytest.mark.parametrize("phrase", [
    "read my screen", "read the error", "what does this say",
    "what is the text",
])
def test_reading_phrases_are_claimed_by_ocr_and_disclaimed_by_the_vlm(phrase):
    """The planner picks by description. If both tools claim the same phrase
    the choice is a coin flip, and it landed wrong in a rehearsal."""
    ocr = REGISTRY["ocr_screen"].description.lower()
    vlm = REGISTRY["describe_screen"].description.lower()

    assert phrase in ocr, f"ocr_screen does not claim {phrase!r}"
    assert phrase in vlm, (
        f"describe_screen should name {phrase!r} in order to disclaim it"
    )


def test_the_vlm_description_points_at_ocr_and_admits_its_cost():
    vlm = REGISTRY["describe_screen"].description
    assert "ocr_screen" in vlm, "describe_screen must redirect text requests"
    assert "not" in vlm.lower(), "the redirect must be an instruction, not a hint"
    assert "35 second" in vlm or "slow" in vlm.lower(), (
        "a 35s tool must say so; the planner has no other way to know"
    )


def test_ocr_advertises_being_the_fast_path():
    ocr = REGISTRY["ocr_screen"].description.lower()
    assert "fast" in ocr or "3 second" in ocr
