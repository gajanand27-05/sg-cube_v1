import logging
from typing import Any, Optional

from backend.core.events import bus
from backend.daemon.ui_events import ConfidenceEvent, ConfidenceScore

log = logging.getLogger(__name__)


class ObservabilityEngine:
    """The central engine for scoring system confidence and reliability."""

    def __init__(self):
        # Maps request_id -> current metrics being accumulated
        self._current_metrics: dict[str, dict[str, Any]] = {}

    def report_ai_quality(self, request_id: str, score: float, detail: str):
        """Called by the Verifier layer."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": []}
        self._current_metrics[request_id]["ai"].append((score, detail))
        self._publish_update(request_id)

    def report_tool_quality(self, request_id: str, score: float, detail: str):
        """Called by the Runtime layer."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": []}
        self._current_metrics[request_id]["tool"].append((score, detail))
        self._publish_update(request_id)

    def report_context_quality(self, request_id: str, score: float, detail: str):
        """Called during Intent resolution or by the Verifier."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": []}
        self._current_metrics[request_id]["context"].append((score, detail))
        self._publish_update(request_id)

    def _publish_update(self, request_id: str):
        metrics = self._current_metrics[request_id]
        
        # Simple averages for now
        def avg(key):
            scores = [s[0] for s in metrics.get(key, [])]
            return sum(scores) / len(scores) if scores else 100.0

        score = ConfidenceScore(
            tool_quality=avg("tool"),
            ai_quality=avg("ai"),
            context_quality=avg("context")
        )
        
        bus.publish(ConfidenceEvent(
            request_id=request_id,
            score=score,
            details=metrics
        ))


# Global instance
engine = ObservabilityEngine()
