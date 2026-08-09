import logging
from typing import Any, Optional

from backend.core.events import get_bus
from backend.daemon.ui_events import ConfidenceEvent, ReliabilityMetrics

log = logging.getLogger(__name__)

# There is no end-of-request hook to pop per-request buckets on, and the sample
# lists are sum()-ed on every publish, so both are bounded here. Without this the
# engine is a pure leak: a long-lived daemon accumulates one dict per request_id
# forever and every tool call costs O(total tool calls ever).
MAX_TRACKED_REQUESTS = 100
MAX_SAMPLES = 500

# Fallback success threshold when a caller reports a raw confidence score with no
# explicit success flag. Real tools return 60.0-98.0 on success (see
# ToolResult.success call sites) and 0.0-20.0 on error/blocked, so the previous
# `>= 100.0` booked almost every successful tool as a failure. Callers that know
# the ToolStatus should pass success= explicitly rather than rely on this.
SUCCESS_CONFIDENCE_THRESHOLD = 50.0


def _append_capped(samples: list[float], value: float) -> None:
    samples.append(value)
    if len(samples) > MAX_SAMPLES:
        del samples[:-MAX_SAMPLES]


class ObservabilityEngine:
    """The central engine for tracking concrete system reliability metrics."""

    def __init__(self):
        # Maps request_id -> current metrics being accumulated (bounded, LRU-ish:
        # oldest inserted request is evicted once MAX_TRACKED_REQUESTS is passed)
        self._current_metrics: dict[str, dict[str, Any]] = {}

        # Global accumulated stats (session-wide)
        self._total_tools = 0
        self._successful_tools = 0
        self._latencies: list[float] = []
        self._recall_scores: list[float] = []
        self._hallucination_passed = 0
        self._hallucination_total = 0

    def _bucket(self, request_id: str) -> dict[str, Any]:
        """Per-request accumulator, created on demand and bounded.

        Also the reason report_latency no longer KeyErrors: it used to call
        _publish_update for a request_id it had never registered.
        """
        bucket = self._current_metrics.get(request_id)
        if bucket is None:
            bucket = {"ai": [], "tool": [], "context": [], "latency": 0}
            self._current_metrics[request_id] = bucket
            while len(self._current_metrics) > MAX_TRACKED_REQUESTS:
                self._current_metrics.pop(next(iter(self._current_metrics)), None)
        return bucket

    def report_ai_quality(self, request_id: str, score: float, detail: str):
        """Called by the Verifier layer for hallucination and logic checks."""
        self._bucket(request_id)["ai"].append((score, detail))

        # Track as hallucination check
        self._hallucination_total += 1
        if score >= 80.0: # Threshold for 'pass'
            self._hallucination_passed += 1

        self._publish_update(request_id)

    def report_tool_quality(self, request_id: str, score: float, detail: str,
                            success: Optional[bool] = None):
        """Called by the Runtime layer for tool execution results.

        `success` is the authoritative outcome (the caller's ToolStatus). When
        omitted the score is compared against SUCCESS_CONFIDENCE_THRESHOLD.

        Runtime.run_tool is the single owner of this call — every tool execution
        funnels through it (Tool.__call__ -> runtime.run_tool), including the
        timeout and crash paths. Operator used to report a second time for the
        subset of calls it made, which inflated both the numerator and the
        denominator of the success rate.
        """
        self._bucket(request_id)["tool"].append((score, detail))

        # Track for success rate
        succeeded = success if success is not None else score >= SUCCESS_CONFIDENCE_THRESHOLD
        self._total_tools += 1
        if succeeded:
            self._successful_tools += 1

        self._publish_update(request_id)

    def report_context_quality(self, request_id: str, score: float, detail: str):
        """Called for memory retrieval accuracy."""
        self._bucket(request_id)["context"].append((score, detail))
        _append_capped(self._recall_scores, score)
        self._publish_update(request_id)

    def report_latency(self, request_id: str, ms: int):
        """Called when a request finishes to track response times."""
        _append_capped(self._latencies, ms / 1000.0)
        self._bucket(request_id)["latency"] = ms
        self._publish_update(request_id)

    def _publish_update(self, request_id: str):
        metrics_data = self._bucket(request_id)

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
