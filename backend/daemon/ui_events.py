"""Typed events emitted by trigger.handle_wake() and consumed by the Textual UI.

Using dataclasses lets us pattern-match in the UI dispatcher and stay decoupled
from the daemon internals.
"""
from dataclasses import dataclass


@dataclass
class WakeHeard:
    peak: int  # peak amplitude of the captured audio buffer, 0..32767


@dataclass
class CommandTranscribed:
    text: str
    peak: int


@dataclass
class IntentResolved:
    action: str
    target: str
    source_layer: str  # "cache" | "rule" | "llm"


@dataclass
class Executed:
    command: str
    status: str  # "success" | "blocked" | "error"
    message: str | None
    reason: str | None
    latency_ms: int
    confidence: float = 100.0
    confidence_reason: list[str] = None


@dataclass
class SpokenResponse:
    text: str


@dataclass
class ClipboardChangedEvent:
    text: str


@dataclass
class HandoverEvent:
    url: str | None = None
    text: str | None = None
    htype: str = "general" # renamed to htype to avoid conflict with builtin type


@dataclass
class TriggerError:
    detail: str


@dataclass
class VerificationEvent:
    tool_name: str
    is_valid: bool
    error: str | None = None


@dataclass
class ReliabilityMetrics:
    tool_success_rate: float    # 0.0 - 100.0
    avg_response_sec: float     # e.g., 1.2
    memory_recall_pct: float    # 0.0 - 100.0
    hallucination_passed: int
    hallucination_total: int


@dataclass
class ConfidenceEvent:
    request_id: str
    metrics: ReliabilityMetrics
    details: dict = None


@dataclass
class SelfHealingEvent:
    tool_name: str
    error: str
    path: str


@dataclass
class InternalAgentEvent:
    agent_name: str
    action: str
    details: dict


@dataclass
class TokenStreamEvent:
    agent_name: str
    token: str
    full_content: str


@dataclass
class AgentThinkingEvent:
    agent_name: str
    is_thinking: bool


@dataclass
class ProactiveEvent:
    query: str


@dataclass
class SystemStatsEvent:
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    net_down_bps: float
    net_up_bps: float
    temp_c: float | None = None


@dataclass
class ToolStartedEvent:
    tool_name: str
    args: dict


@dataclass
class ToolFinishedEvent:
    tool_name: str
    status: str
    result: str | None = None
    error: str | None = None
    latency_ms: int = 0


@dataclass
class MemoryHitEvent:
    query: str
    source: str
    results_count: int


@dataclass
class VisionUpdateEvent:
    description: str
    windows: list | None = None
