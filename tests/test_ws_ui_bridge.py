"""The center-column panels hang off five events — verify the wire seam.

Before this, STTPartialEvent was published and subscribed by no one in
ws_ui.py: the bridge's TYPE_MAP never mapped it, so the web UI never saw
stt_partial no matter how much the assistant transcribed. A panel built on
an unbridged event is permanently empty and looks like a WebSocket bug.
These asserts are the tripwire for that class of failure.
"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.daemon.ui_events import (
    AIMetricsEvent,
    ConfidenceEvent,
    ReliabilityMetrics,
    STTPartialEvent,
    TokenStreamEvent,
    ToolFinishedEvent,
    ToolStartedEvent,
)
from backend.server.ws_ui import TYPE_MAP, UIEventManager


def test_center_column_events_are_bridged():
    assert TYPE_MAP[STTPartialEvent] == "stt_partial"
    assert TYPE_MAP[TokenStreamEvent] == "token_stream"
    assert TYPE_MAP[ConfidenceEvent] == "confidence"
    assert TYPE_MAP[ToolStartedEvent] == "tool_started"
    assert TYPE_MAP[ToolFinishedEvent] == "tool_finished"
    # AIMetricsEvent was imported here and never asserted. It drives the AI Core
    # panel's live readout, which is one of the always-on surfaces — an unbridged
    # one reads as a dead backend rather than a missing map entry.
    assert TYPE_MAP[AIMetricsEvent] == "ai_metrics"


def test_events_survive_the_websocket_serializer():
    """Nested dataclasses (ConfidenceEvent.metrics) must come out as flat
    JSON — the same TypeError-in-broadcast failure mode as MemoryHitEvent."""
    serializer = UIEventManager()._serialize
    events = [
        STTPartialEvent(text="say hi", is_final=False),
        TokenStreamEvent(agent_name="planner", token="hi", full_content="hi there"),
        ConfidenceEvent(
            request_id="r1",
            metrics=ReliabilityMetrics(
                tool_success_rate=95.0,
                avg_response_sec=1.2,
                memory_recall_pct=88.0,
                hallucination_passed=1,
                hallucination_total=2,
            ),
            details={"latency": 900},
        ),
        ToolStartedEvent(tool_name="web_search", args={"q": "x"}),
        ToolFinishedEvent(tool_name="web_search", status="success", latency_ms=800),
    ]
    for event in events:
        decoded = json.loads(json.dumps(serializer(event)))
        assert decoded, f"{type(event).__name__} must serialize to non-empty JSON"

    conf = json.loads(json.dumps(serializer(events[2])))
    # _serialize flattens the nested ReliabilityMetrics into metric_* keys
    # (ws_ui.py) — that is the wire contract the ConfidencePanel reads.
    assert conf["metric_tool_success_rate"] == 95.0
    assert conf["metric_memory_recall_pct"] == 88.0
    assert "metrics" not in conf
