"""Phase 4C — per-turn latency instrumentation.

One `TurnLatency` per voice/text turn. `mark(stage)` records the ms
elapsed since the turn began. `record()` on the singleton ledger pins
the breakdown for `/diagnostics/latency` to surface later.

Stages of interest (in order):
    wake                → t=0 (VAD onset)
    stt_done            → transcribe_array returned
    orchestrator_route  → BrainRequest built, about to enter brain
    context_ready       → Brain finished context assembly (from run_stream)
    planner_first_token → LLM produced its first token
    first_tool_start    → first tool call began (if any)
    first_tool_end      → first tool call returned (if any)
    first_audio_out     → first sentence dispatched to Piper
    total               → end of the turn

Stages are optional — missing stages just don't appear in the breakdown.
That way a text-only turn (no wake, no audio) reports the stages it
actually crossed rather than filling in zeros.
"""
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TurnLatency:
    request_id: str
    mode: str = "voice"  # "voice" | "text" | "proactive"
    _start_perf: float = field(default_factory=time.perf_counter)
    stages: dict[str, int] = field(default_factory=dict)  # stage → ms since start
    _sealed: bool = False

    def mark(self, stage: str) -> None:
        """Record the elapsed ms for `stage`. Idempotent per stage — the
        first mark wins so repeated calls (e.g. per token) don't overwrite
        `planner_first_token` with the LAST token's time."""
        if self._sealed:
            return
        if stage in self.stages:
            return
        self.stages[stage] = int((time.perf_counter() - self._start_perf) * 1000)

    def seal(self) -> None:
        """Freeze the record and stamp `total`. Called once at turn end."""
        if self._sealed:
            return
        self.stages.setdefault("total", int((time.perf_counter() - self._start_perf) * 1000))
        self._sealed = True

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "mode": self.mode,
            "stages_ms": dict(self.stages),
        }


class LatencyLedger:
    """Bounded ring buffer of recent turn breakdowns.

    Not persistent — dies with the process. That's the right trade-off
    here since Phase 4C is about "which hop is slow right now" not
    long-run trend analysis; the dogfooding ledger already covers the
    persistent per-turn totals.
    """

    def __init__(self, capacity: int = 100):
        self._turns: deque[dict] = deque(maxlen=capacity)

    def record(self, turn: TurnLatency) -> None:
        turn.seal()
        self._turns.append(turn.to_dict())

    def recent(self, n: int = 20) -> list[dict]:
        n = max(1, min(n, len(self._turns)))
        return list(self._turns)[-n:]

    def clear(self) -> None:
        self._turns.clear()


_LEDGER: LatencyLedger | None = None


def ledger() -> LatencyLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = LatencyLedger()
    return _LEDGER
