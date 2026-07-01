import logging
from typing import Any, Optional

from backend.core.events import get_bus
from backend.daemon.ui_events import ConfidenceEvent, ReliabilityMetrics

log = logging.getLogger(__name__)


class ObservabilityEngine:
    """The central engine for tracking concrete system reliability metrics."""

    def __init__(self):
        # Maps request_id -> current metrics being accumulated
        self._current_metrics: dict[str, dict[str, Any]] = {}
        
        # Global accumulated stats (session-wide)
        self._total_tools = 0
        self._successful_tools = 0
        self._latencies: list[float] = []
        self._recall_scores: list[float] = []
        self._hallucination_passed = 0
        self._hallucination_total = 0

    def report_ai_quality(self, request_id: str, score: float, detail: str):
        """Called by the Verifier layer for hallucination and logic checks."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": [], "latency": 0}
        
        self._current_metrics[request_id]["ai"].append((score, detail))
        
        # Track as hallucination check
        self._hallucination_total += 1
        if score >= 80.0: # Threshold for 'pass'
            self._hallucination_passed += 1
            
        self._publish_update(request_id)

    def report_tool_quality(self, request_id: str, score: float, detail: str):
        """Called by the Runtime layer for tool execution results."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": [], "latency": 0}
        
        self._current_metrics[request_id]["tool"].append((score, detail))
        
        # Track for success rate
        self._total_tools += 1
        if score >= 100.0: # Perfect success
            self._successful_tools += 1
            
        self._publish_update(request_id)

    def report_context_quality(self, request_id: str, score: float, detail: str):
        """Called for memory retrieval accuracy."""
        if request_id not in self._current_metrics:
            self._current_metrics[request_id] = {"ai": [], "tool": [], "context": [], "latency": 0}
        
        self._current_metrics[request_id]["context"].append((score, detail))
        self._recall_scores.append(score)
        self._publish_update(request_id)

    def report_latency(self, request_id: str, ms: int):
        """Called when a request finishes to track response times."""
        sec = ms / 1000.0
        self._latencies.append(sec)
        if request_id in self._current_metrics:
            self._current_metrics[request_id]["latency"] = ms
        self._publish_update(request_id)

    def _publish_update(self, request_id: str):
        metrics_data = self._current_metrics[request_id]
        
        # Tool Success Rate
        success_rate = (self._successful_tools / self._total_tools * 100.0) if self._total_tools else 100.0
        
        # Avg Response
        avg_resp = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        
        # Memory Recall
        avg_recall = sum(self._recall_scores) / len(self._recall_scores) if self._recall_scores else 100.0

        metrics = ReliabilityMetrics(
            tool_success_rate=success_rate,
            avg_response_sec=avg_resp,
            memory_recall_pct=avg_recall,
            hallucination_passed=self._hallucination_passed,
            hallucination_total=self._hallucination_total
        )
        
        get_bus().publish(ConfidenceEvent(
            request_id=request_id,
            metrics=metrics,
            details=metrics_data
        ))


# Global instance
engine = ObservabilityEngine()
