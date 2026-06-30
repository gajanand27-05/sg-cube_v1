"""Deterministic Replay System — flight recorder for the AI pipeline."""
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.core.events import get_bus
from backend.daemon.ui_events import (
    CommandTranscribed, IntentResolved, Executed, SpokenResponse,
    TokenStreamEvent, ToolStartedEvent, ToolFinishedEvent
)

log = logging.getLogger(__name__)

REPLAY_DIR = Path(__file__).resolve().parents[3] / "backend" / "database" / "replays"
REPLAY_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ReplayFrame:
    """Single frame in the execution trace."""
    timestamp: str
    stage: str  # "stt", "context", "planner_token", "guardian", "tool_start", "tool_end", "tts", "final"
    data: dict
    latency_ms: int = 0


@dataclass
class ExecutionTrace:
    """Complete execution trace for one request."""
    request_id: str
    user_id: str
    input_text: str
    input_mode: str
    start_time: str
    end_time: str | None = None
    total_latency_ms: int = 0
    frames: list[ReplayFrame] = field(default_factory=list)
    final_response: str | None = None
    status: str = "running"  # "running" | "success" | "error"
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class ReplayRecorder:
    """Records execution traces in real-time."""
    
    def __init__(self, request_id: str, user_id: str, input_text: str, input_mode: str):
        self.trace = ExecutionTrace(
            request_id=request_id,
            user_id=user_id,
            input_text=input_text,
            input_mode=input_mode,
            start_time=datetime.now().isoformat(),
        )
        self._enabled = True
        self._stage_start_times: dict[str, float] = {}
    
    def start_stage(self, stage: str) -> None:
        import time
        self._stage_start_times[stage] = time.perf_counter()
    
    def end_stage(self, stage: str) -> int:
        import time
        start = self._stage_start_times.pop(stage, time.perf_counter())
        return int((time.perf_counter() - start) * 1000)
    
    def add_frame(self, stage: str, data: dict, latency_ms: int = 0) -> None:
        if not self._enabled:
            return
        frame = ReplayFrame(
            timestamp=datetime.now().isoformat(),
            stage=stage,
            data=data,
            latency_ms=latency_ms,
        )
        self.trace.frames.append(frame)
        log.debug(f"Replay frame: {stage} ({latency_ms}ms)")
    
    def finish(self, response: str | None = None, status: str = "success", error: str | None = None) -> None:
        self.trace.end_time = datetime.now().isoformat()
        self.trace.final_response = response
        self.trace.status = status
        self.trace.error = error
        import time
        start = datetime.fromisoformat(self.trace.start_time)
        end = datetime.fromisoformat(self.trace.end_time)
        self.trace.total_latency_ms = int((end - start).total_seconds() * 1000)
        self._enabled = False
        self._save()
    
    def _save(self) -> None:
        """Persist trace to disk."""
        path = REPLAY_DIR / f"{self.trace.request_id}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.trace), f, indent=2, default=str)
            log.info(f"Replay saved: {path}")
        except Exception as e:
            log.error(f"Failed to save replay: {e}")


class ReplayPlayer:
    """Plays back a recorded execution trace."""
    
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.trace: ExecutionTrace | None = None
    
    def load(self) -> bool:
        path = REPLAY_DIR / f"{self.request_id}.json"
        if not path.exists():
            log.error(f"Replay not found: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.trace = ExecutionTrace(**data)
            # Reconstruct frames
            self.trace.frames = [ReplayFrame(**f) for f in data.get("frames", [])]
            log.info(f"Replay loaded: {len(self.trace.frames)} frames")
            return True
        except Exception as e:
            log.error(f"Failed to load replay: {e}")
            return False
    
    def get_summary(self) -> dict:
        if not self.trace:
            return {}
        return {
            "request_id": self.trace.request_id,
            "input_text": self.trace.input_text,
            "total_frames": len(self.trace.frames),
            "total_latency_ms": self.trace.total_latency_ms,
            "status": self.trace.status,
            "stages": list(set(f.stage for f in self.trace.frames)),
        }
    
    def get_stage_timing(self) -> dict[str, list[int]]:
        """Get latency per stage."""
        if not self.trace:
            return {}
        timing: dict[str, list[int]] = {}
        for frame in self.trace.frames:
            timing.setdefault(frame.stage, []).append(frame.latency_ms)
        return {k: {"count": len(v), "avg": sum(v)/len(v), "max": max(v)} for k, v in timing.items()}
    
    def filter_frames(self, stage: str) -> list[ReplayFrame]:
        if not self.trace:
            return []
        return [f for f in self.trace.frames if f.stage == stage]


# Global registry of active recorders
_active_recorders: dict[str, ReplayRecorder] = {}


def start_recording(request_id: str, user_id: str, input_text: str, input_mode: str) -> ReplayRecorder:
    """Start recording a new trace."""
    recorder = ReplayRecorder(request_id, user_id, input_text, input_mode)
    _active_recorders[request_id] = recorder
    return recorder


def get_recorder(request_id: str) -> ReplayRecorder | None:
    return _active_recorders.get(request_id)


def stop_recording(request_id: str, response: str | None = None, status: str = "success", error: str | None = None) -> None:
    recorder = _active_recorders.pop(request_id, None)
    if recorder:
        recorder.finish(response, status, error)


# Event bus integration
def _register_event_handlers():
    """Register event handlers to auto-record from event bus."""
    bus = get_bus()
    
    def on_command_transcribed(event: CommandTranscribed):
        recorder = _active_recorders.get(event.__dict__.get("request_id"))
        if recorder:
            recorder.add_frame("stt", {"text": event.text, "peak": event.peak})
    
    def on_intent_resolved(event: IntentResolved):
        recorder = next((r for r in _active_recorders.values() if True), None)
        if recorder:
            recorder.add_frame("intent", {"action": event.action, "target": event.target, "source": event.source_layer})
    
    def on_tool_started(event: ToolStartedEvent):
        recorder = next((r for r in _active_recorders.values() if True), None)
        if recorder:
            recorder.add_frame("tool_start", {"tool": event.tool_name, "args": event.args})
    
    def on_tool_finished(event: ToolFinishedEvent):
        recorder = next((r for r in _active_recorders.values() if True), None)
        if recorder:
            recorder.add_frame("tool_end", {"tool": event.tool_name, "status": event.status, "latency_ms": event.latency_ms})
    
    def on_spoken_response(event: SpokenResponse):
        recorder = next((r for r in _active_recorders.values() if True), None)
        if recorder:
            recorder.add_frame("tts", {"text": event.text})
    
    # Register (will be called when event bus is ready)
    return {
        CommandTranscribed: on_command_transcribed,
        IntentResolved: on_intent_resolved,
        ToolStartedEvent: on_tool_started,
        ToolFinishedEvent: on_tool_finished,
        SpokenResponse: on_spoken_response,
    }