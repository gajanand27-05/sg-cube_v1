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
class AgentReasoningEvent:
    agent_name: str
    reasoning: str


@dataclass
class AgentToolCallEvent:
    agent_name: str
    tool: str
    args: dict | None = None
    result: str | None = None
    latency_ms: int = 0


@dataclass
class AgentCompletedEvent:
    agent_name: str
    status: str          # "completed" | "failed" | "verified"
    confidence: float = 100.0
    latency_ms: int = 0
    summary: str | None = None


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
class MemoryHit:
    """A single retrieval result surfaced by a memory search."""
    title: str
    score: float          # 0.0 - 1.0 combined relevance
    source: str           # e.g. "semantic_memory" | "notes"


@dataclass
class MemoryHitEvent:
    query: str
    source: str
    results_count: int
    hits: list[MemoryHit] | None = None   # rich results when available


@dataclass
class DetectedObject:
    """A thing the vision model saw on screen."""
    label: str
    confidence: float     # 0.0 - 1.0


@dataclass
class VisionUpdateEvent:
    description: str
    windows: list | None = None
    objects: list[DetectedObject] | None = None
    ocr: list[str] | None = None


@dataclass
class STTPartialEvent:
    """Partial transcript from streaming STT."""
    text: str
    is_final: bool = False


@dataclass
class TTSStartEvent:
    text: str


@dataclass
class TTSChunkEvent:
    text: str
    progress: float  # 0.0 - 1.0


@dataclass
class TTSEndEvent:
    text: str


@dataclass
class ProviderDegradedEvent:
    """Phase 5B: an LLM provider hit a transient failure (429 / 5xx / timeout).

    Fired whenever the resilient LLMProvider wrapper retries or falls
    over to a backup backend. The UI can render "Planner provider
    rate-limited, retrying" or "Falling over to <backup>" instead of
    the user seeing a silent hang or a generic error.
    """
    backend: str          # e.g. "gemini"
    reason: str           # short human string, e.g. "429 rate-limited"
    action: str           # "retry" | "fallback" | "gave_up"
    fallback: str = ""    # backend name we fell over to, if action=="fallback"


@dataclass
class SpeechInterruptedEvent:
    """Phase 4A: user spoke while TTS was playing → we cut it off (barge-in).

    Distinct from a normal wake-word trigger so the frontend can reflect
    the specific "you interrupted me" transition (Speaking → Listening)
    rather than the neutral wake path.
    """
    rms: float  # peak RMS of the trigger chunk (int16 amplitude scale)


@dataclass
class AIMetricsEvent:
    """Single source of truth for live AI performance telemetry."""
    tokens_per_second: float
    latency_ms: int
    inference_ms: int
    queue_depth: int
    tool_calls: int
    active_model: str


@dataclass
class CanvasUpdateEvent:
    """Phase 3: assistant populated the canvas via render_canvas.

    `widgets` is a validated list of widget dicts (metric/list/map/chart/text)
    that already passed the strict server-side schema. Frontend maps each
    entry's `type` to a typed React component and renders props as plain
    text (no dangerouslySetInnerHTML)."""
    widgets: list
