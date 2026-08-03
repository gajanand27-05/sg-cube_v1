"""T-planner-canvas-chain: iteration-2 instruction swap.

Commander cues the planner with "Summarize results for the user." after tool
results — which on canvas-intent queries lets the model fabricate a render
claim instead of calling render_canvas (2/9 in the chain probe). The swap
must fire for canvas phrasings and leave ordinary queries untouched.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.commander import _iteration_instruction

RENDER = "Now call render_canvas"
PLAIN = "Summarize results for the user."


def test_canvas_phrasings_get_render_instruction():
    for q in [
        "Show me AAPL and the news",
        "Show me AAPL on the canvas and the top news headlines",
        "Put Apple stock and world news on the canvas",
        "Display the weather dashboard",
        "Render a chart of GPU usage",
    ]:
        assert _iteration_instruction(q).startswith(RENDER), q


def test_non_canvas_queries_keep_summary_instruction():
    for q in [
        "What is the capital of France?",
        "Summarize today's meetings",
        "Send an email to John",
        "Set a timer for 5 minutes",
    ]:
        assert _iteration_instruction(q) == PLAIN, q
