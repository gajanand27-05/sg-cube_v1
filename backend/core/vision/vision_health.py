"""VisionClaw Phase 4 — the vision pipeline's health numbers, measured.

Before this module the health event was assembled inline in the WS loop with
two stubs: `fps_processed` was `min(fps_received, max_fps)` (an assumption
about the throttle, not a count of frames the detector ran on) and
`tts_queue_depth` was a hardcoded 0. Both looked like data.

The one rule here: **absence is reported as None, never as 0.0.** A counter
that nobody feeds reads as "no data" in the snapshot, so a half-wired
pipeline is visible at /diagnostics/vision instead of looking like a healthy
idle one. This repo has shipped four separate "defined but never
constructed" bugs; None is what makes the fifth loud.

Who feeds what (neither side owns the state — this module does):
  * WS receive loop  -> note_frame_received(...)  for every binary frame
  * DetectionRunner  -> note_frame_processed(...) when inference completes
  * frame_ingestor   -> read directly for throttle drops (it already counts
                        them; duplicating that counter would be a second
                        source of truth)
  * tts_queue        -> read directly via its public depth accessor

fps_processed is genuinely lower than fps_received: DetectionRunner skips a
frame whose predecessor is still in flight, and the ingestor throttles to
max_fps. That gap is the useful signal, which is exactly why it must be
counted rather than derived.

ponytail: fixed-width rolling window of timestamps, pruned on write. O(n) per
prune with n = frames in the last WINDOW_S (~10 at 2fps), so the list is
cheaper than a deque with bookkeeping. Upgrade path if the pipeline ever runs
at video rate: collections.deque + popleft while stale.
"""
import threading
import time
from dataclasses import asdict, dataclass

# Rolling window both fps figures are measured over.
WINDOW_S = 5.0
# No frame received for this long => the source is dead, so the rates are
# unknown rather than zero. Two health ticks (HEALTH_INTERVAL_S = 5s).
STALE_AFTER_S = 10.0
# Plan's Phase 4 rule: "drop processing if latency > 1.5s". The drop decision
# lives in the WS loop; the threshold lives here so the number the loop drops
# on and the number this module reports staleness against are the same one.
STALE_FRAME_MS = 1500.0


@dataclass(frozen=True)
class VisionHealthSnapshot:
    """One read of the pipeline. `None` means "not measured", never "zero"."""

    # Rates over the last WINDOW_S. None when the feed is stale or never fed.
    fps_received: float | None
    fps_processed: float | None
    # Last completed detection. None until the detector has reported once.
    detector_latency_ms: float | None
    # Pending TTS sentences. None when no turn has ever built a queue.
    tts_queue_depth: int | None
    # Frames the ingestor threw away to hold max_fps (cumulative).
    dropped_frames: int
    # End-to-end frame age: server receive time - phone capture time. None
    # until the phone sends a capture timestamp.
    frame_age_ms: float | None
    frame_age_avg_ms: float | None
    frames_dropped_stale: int
    # Cumulative counts, so "0 frames ever" is distinguishable from "idle now".
    frames_received: int
    frames_processed: int
    # True when nothing has fed note_frame_received recently (or ever).
    stale: bool
    # Seconds since the last received frame; None if none was ever received.
    age_s: float | None
    mode: str | None

    def as_dict(self) -> dict:
        return asdict(self)

    def event_fields(self) -> dict:
        """Kwargs for daemon.ui_events.VisionHealthEvent, whose fields are
        non-optional scalars. Unmeasured values become -1, NOT 0: a HUD
        rendering 0 fps reads as "measured zero", which is the exact lie this
        module exists to prevent. Widen those fields to `| None` and this
        helper goes away.
        """
        return {
            "fps_received": self.fps_received if self.fps_received is not None else -1.0,
            "fps_processed": self.fps_processed if self.fps_processed is not None else -1.0,
            "detector_latency_ms": (
                self.detector_latency_ms if self.detector_latency_ms is not None else -1.0
            ),
            "tts_queue_depth": self.tts_queue_depth if self.tts_queue_depth is not None else -1,
            "dropped_frames": self.dropped_frames,
            "mode": self.mode or "idle",
        }


def _rate(times: list[float], now: float, window_s: float) -> float:
    """Frames per second over the observed span, not the nominal window.

    Dividing by window_s would under-report a session that is only 1s old by
    5x, which reads as "the detector is falling behind" on every reconnect.
    """
    if not times:
        return 0.0
    span = min(window_s, max(now - times[0], 0.5))
    return round(len(times) / span, 2)


class VisionHealth:
    """Owns the vision pipeline's counters. Thread-safe: the WS loop and the
    detector run on the uvicorn loop, HTTP handlers on worker threads."""

    def __init__(self, window_s: float = WINDOW_S, stale_after_s: float = STALE_AFTER_S):
        self.window_s = window_s
        self.stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._received: list[float] = []
        self._processed: list[float] = []
        self._ages: list[tuple[float, float]] = []  # (t, age_ms)
        self._frames_received = 0
        self._frames_processed = 0
        self._frames_dropped_stale = 0
        self._last_latency_ms: float | None = None
        self._last_age_ms: float | None = None
        self._last_received_at: float | None = None
        self._last_processed_at: float | None = None

    # ── writers ──────────────────────────────────────────────────────────
    def note_frame_received(
        self, age_ms: float | None = None, dropped_stale: bool = False
    ) -> None:
        """One binary frame arrived on the WS. Call for EVERY frame, before
        any throttle or staleness decision.

        age_ms: server receive time - phone capture time, if the phone sent a
                capture timestamp. None when it did not (Phase 1-3 phones).
        dropped_stale: True when the caller is discarding this frame for being
                older than STALE_FRAME_MS. It still counts as received — that
                is what makes the drop rate meaningful.
        """
        now = time.monotonic()
        with self._lock:
            self._frames_received += 1
            self._last_received_at = now
            self._received.append(now)
            self._prune(now)
            if age_ms is not None:
                self._last_age_ms = float(age_ms)
                self._ages.append((now, float(age_ms)))
            if dropped_stale:
                self._frames_dropped_stale += 1

    def note_frame_processed(self, latency_ms: float | None = None) -> None:
        """The detector finished inference on a frame. Called from
        DetectionRunner.submit(), NOT from the WS loop: the loop cannot know
        whether submit() ran or skipped-because-busy, and that gap is the
        number we are here to measure."""
        now = time.monotonic()
        with self._lock:
            self._frames_processed += 1
            self._last_processed_at = now
            self._processed.append(now)
            self._prune(now)
            if latency_ms is not None:
                self._last_latency_ms = float(latency_ms)

    def reset(self) -> None:
        """Phone disconnected. Clears the windows and the "have we ever been
        fed" markers so the next snapshot reports absence, not the last
        session's rates. Cumulative counters survive, matching
        FrameIngestor.reset()."""
        with self._lock:
            self._received.clear()
            self._processed.clear()
            self._ages.clear()
            self._last_latency_ms = None
            self._last_age_ms = None
            self._last_received_at = None
            self._last_processed_at = None

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self._received = [t for t in self._received if t > cutoff]
        self._processed = [t for t in self._processed if t > cutoff]
        self._ages = [p for p in self._ages if p[0] > cutoff]

    # ── reader ───────────────────────────────────────────────────────────
    def snapshot(self, mode: str | None = None) -> VisionHealthSnapshot:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            age_s = None if self._last_received_at is None else round(now - self._last_received_at, 2)
            stale = age_s is None or age_s > self.stale_after_s

            fps_received = None if stale else _rate(self._received, now, self.window_s)
            # Fed-but-idle is a real 0.0 (the detector died); never-fed is None
            # (the detector was never wired to this module at all).
            if stale or self._last_processed_at is None:
                fps_processed = None
            else:
                fps_processed = _rate(self._processed, now, self.window_s)

            avg_age = (
                round(sum(a for _, a in self._ages) / len(self._ages), 1)
                if self._ages else None
            )
            return VisionHealthSnapshot(
                fps_received=fps_received,
                fps_processed=fps_processed,
                detector_latency_ms=self._last_latency_ms,
                tts_queue_depth=tts_queue_depth(),
                dropped_frames=_ingestor_dropped(),
                frame_age_ms=self._last_age_ms,
                frame_age_avg_ms=avg_age,
                frames_dropped_stale=self._frames_dropped_stale,
                frames_received=self._frames_received,
                frames_processed=self._frames_processed,
                stale=stale,
                age_s=age_s,
                mode=mode,
            )


def tts_queue_depth() -> int | None:
    """Sentences waiting in the streaming-TTS queue, or None if no turn has
    ever built one (module singleton still unconstructed).

    Read-only and cross-loop safe: SentenceQueue.depth is asyncio.Queue.qsize(),
    a deque length — it never touches the loop the queue is bound to, which is
    the hazard T-tts-loop-globals documents. It can transiently include the
    end-of-turn sentinel, so treat 1 as "about to be empty".
    """
    try:
        from backend.ai_modules.speech.tts_queue import sentence_queue_depth
        return sentence_queue_depth()
    except Exception:  # speech stack absent (headless test/CI) — unknown, not 0
        return None


def _ingestor_dropped() -> int:
    try:
        from backend.core.vision.frame_ingest import frame_ingestor
        return int(frame_ingestor.stats["frames_dropped"])
    except Exception:
        return 0


# One pipeline per process, same shape as frame_ingestor / detection_runner.
vision_health = VisionHealth()
