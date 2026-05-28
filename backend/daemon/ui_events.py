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


@dataclass
class SpokenResponse:
    text: str


@dataclass
class TriggerError:
    detail: str


@dataclass
class VerificationEvent:
    tool_name: str
    is_valid: bool
    error: str | None = None


@dataclass
class ConfidenceScore:
    tool_quality: float
    ai_quality: float
    context_quality: float

    @property
    def aggregate(self) -> float:
        return (self.tool_quality + self.ai_quality + self.context_quality) / 3.0


@dataclass
class ConfidenceEvent:
    request_id: str
    score: ConfidenceScore
