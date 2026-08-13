"""VisionClaw Phase 4 — the health numbers must be measurements, not guesses.

The stub this replaces reported `fps_processed = min(fps_received, max_fps)`
and `tts_queue_depth = 0`. Both are shapes that pass a `>= 0` assertion while
being pure fiction, so every test here asserts something a fake value would
fail:

  * processed < received when the detector skipped frames
  * an unfed counter reports None, not 0.0 (the "defined but never wired"
    failure mode this repo has shipped four times)
  * a stale feed reports None, not the last session's rates
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.vision.vision_health import (
    STALE_FRAME_MS,
    VisionHealth,
    tts_queue_depth,
)

LOOPBACK = ("127.0.0.1", 4000)


@pytest.fixture()
def health():
    return VisionHealth()


# ── the gap between received and processed is the whole point ────────────

def test_processed_is_lower_than_received_when_the_detector_skips(health):
    """DetectionRunner drops a frame whose predecessor is still in flight. If
    fps_processed were derived from fps_received (the old stub) these two
    would be equal and the skip would be invisible."""
    for i in range(20):
        health.note_frame_received()
        if i % 4 == 0:  # detector kept up with 1 in 4
            health.note_frame_processed(latency_ms=120.0)

    snap = health.snapshot()
    assert snap.frames_received == 20
    assert snap.frames_processed == 5
    assert snap.fps_processed < snap.fps_received
    # Not a rounding artefact — roughly the 1:4 ratio that actually happened.
    assert snap.fps_processed == pytest.approx(snap.fps_received / 4, rel=0.2)
    assert snap.detector_latency_ms == 120.0


def test_unfed_detector_reports_none_not_zero(health):
    """The half-wiring tripwire: frames flowing, detector never calling in.
    A 0.0 here would read as 'detector running, nothing to do'."""
    for _ in range(5):
        health.note_frame_received()

    snap = health.snapshot()
    assert snap.fps_received > 0
    assert snap.fps_processed is None
    assert snap.detector_latency_ms is None
    assert snap.stale is False


def test_never_fed_at_all_reports_absence(health):
    snap = health.snapshot()
    assert snap.stale is True
    assert snap.age_s is None
    assert snap.fps_received is None
    assert snap.fps_processed is None
    assert snap.frames_received == 0


def test_stale_feed_reports_none_not_last_known_rate():
    """Phone dropped off Wi-Fi. Reporting the last measured fps would show a
    live feed for a dead one — the frozen-image failure mode."""
    h = VisionHealth(window_s=0.05, stale_after_s=0.05)
    h.note_frame_received()
    assert h.snapshot().fps_received > 0
    time.sleep(0.1)

    snap = h.snapshot()
    assert snap.stale is True
    assert snap.fps_received is None
    assert snap.fps_processed is None
    assert snap.frames_received == 1  # cumulative count survives


def test_detector_that_died_reports_a_real_zero(health):
    """Fed-once-then-stopped is a genuine 0.0, distinct from never-fed None.
    Losing that distinction is losing the signal that YOLO crashed."""
    health.note_frame_processed(latency_ms=90.0)
    time.sleep(0.01)
    health._processed.clear()  # simulate the window ageing out
    health.note_frame_received()

    snap = health.snapshot()
    assert snap.fps_processed == 0.0
    assert snap.fps_processed is not None
    assert snap.detector_latency_ms == 90.0


def test_reset_returns_to_absence(health):
    health.note_frame_received(age_ms=40.0)
    health.note_frame_processed(latency_ms=50.0)
    health.reset()

    snap = health.snapshot()
    assert snap.stale is True
    assert (snap.fps_received, snap.fps_processed) == (None, None)
    assert snap.detector_latency_ms is None
    assert snap.frame_age_ms is None
    assert snap.frames_received == 1  # cumulative, like FrameIngestor.reset()


# ── frame staleness surface ──────────────────────────────────────────────

def test_frame_age_is_reported_and_averaged(health):
    health.note_frame_received(age_ms=100.0)
    health.note_frame_received(age_ms=300.0)

    snap = health.snapshot()
    assert snap.frame_age_ms == 300.0        # last
    assert snap.frame_age_avg_ms == 200.0    # window mean
    assert snap.frames_dropped_stale == 0


def test_stale_frame_drops_are_counted_and_still_count_as_received(health):
    health.note_frame_received(age_ms=100.0)
    health.note_frame_received(age_ms=STALE_FRAME_MS + 500, dropped_stale=True)

    snap = health.snapshot()
    assert snap.frames_dropped_stale == 1
    assert snap.frames_received == 2  # else the drop rate is unmeasurable


def test_no_phone_timestamp_means_unknown_age(health):
    """Phase 1-3 phones send no capture time. Age must be None, not 0ms."""
    health.note_frame_received()
    snap = health.snapshot()
    assert snap.frame_age_ms is None
    assert snap.frame_age_avg_ms is None


# ── TTS queue depth: a real number or None, never a hardcoded 0 ──────────

def test_tts_depth_is_none_before_any_turn(monkeypatch):
    from backend.ai_modules.speech import tts_queue

    monkeypatch.setattr(tts_queue, "_QUEUE", None)
    assert tts_queue_depth() is None
    # ...and reading the metric must not construct the singleton.
    assert tts_queue._QUEUE is None


def test_tts_depth_counts_actual_pending_sentences(monkeypatch):
    import asyncio

    from backend.ai_modules.speech import tts_queue

    q = tts_queue.SentenceQueue()
    monkeypatch.setattr(tts_queue, "_QUEUE", q)

    async def fill():
        await q._queue.put("one")
        await q._queue.put("two")

    asyncio.run(fill())
    assert tts_queue_depth() == 2  # the old stub said 0 here


# ── the consumer: /diagnostics/vision ────────────────────────────────────

@pytest.fixture()
def client():
    from backend.server.routes import diagnostics

    app = FastAPI()
    app.include_router(diagnostics.router)
    return TestClient(app, client=LOOPBACK)


def test_endpoint_exposes_the_snapshot(client, monkeypatch):
    from backend.core.vision import vision_health as vh

    fresh = VisionHealth()
    monkeypatch.setattr(vh, "vision_health", fresh)
    for i in range(8):
        fresh.note_frame_received(age_ms=50.0)
        if i % 2 == 0:
            fresh.note_frame_processed(latency_ms=77.0)

    body = client.get("/diagnostics/vision").json()
    assert body["stale"] is False
    assert body["frames_received"] == 8
    assert body["frames_processed"] == 4
    assert body["fps_processed"] < body["fps_received"]
    assert body["detector_latency_ms"] == 77.0
    assert body["frame_age_ms"] == 50.0
    assert body["phones_connected"] == 0


def test_endpoint_reports_absence_when_nothing_feeds_it(client, monkeypatch):
    """If the WS loop is never wired up, this endpoint must say so."""
    from backend.core.vision import vision_health as vh

    monkeypatch.setattr(vh, "vision_health", VisionHealth())
    body = client.get("/diagnostics/vision").json()
    assert body["stale"] is True
    assert body["fps_received"] is None
    assert body["fps_processed"] is None


def test_endpoint_keeps_the_local_peer_guard():
    from backend.server.routes import diagnostics

    app = FastAPI()
    app.include_router(diagnostics.router)
    assert TestClient(app, client=("192.168.1.50", 4000)).get(
        "/diagnostics/vision").status_code == 403


def test_event_fields_never_fake_a_zero(health):
    """VisionHealthEvent's fields are non-optional scalars, so absence has to
    survive the crossing as -1 rather than becoming a believable 0."""
    fields = health.snapshot().event_fields()
    assert fields["fps_received"] == -1.0
    assert fields["fps_processed"] == -1.0
    assert fields["detector_latency_ms"] == -1.0


def test_an_unreadable_ingestor_is_unknown_drops_not_zero_drops():
    """_ingestor_dropped() returned 0 when the ingestor could not be read,
    which is the single most reassuring number this field can carry: an
    unreachable ingestor rendered as "drop 0", i.e. a perfectly healthy stream,
    on the panel someone checks precisely because the video looks wrong. Its
    neighbour _tts_queue_depth gets this right and says so in a comment.
    """
    import backend.core.vision.vision_health as vh

    assert vh._ingestor_dropped() is not None      # normal path still reports

    class _Boom:
        @property
        def stats(self):
            raise RuntimeError("ingestor gone")

    import backend.core.vision.frame_ingest as fi
    original = fi.frame_ingestor
    fi.frame_ingestor = _Boom()
    try:
        assert vh._ingestor_dropped() is None, "unreadable ingestor must be unknown, not 0"
    finally:
        fi.frame_ingestor = original


def test_unknown_drop_count_crosses_the_wire_as_the_sentinel(health):
    """None has to survive event_fields() as -1 like every other unmeasured
    value — the HUD's measured() gate turns that into an em-dash, while a 0
    would render as a real count."""
    from dataclasses import replace
    snap = replace(health.snapshot(), dropped_frames=None)
    assert snap.event_fields()["dropped_frames"] == -1


def test_a_negative_frame_age_is_a_reading_not_an_absence(health):
    """phone_session.frame_age_ms deliberately refuses to clamp a negative age:
    a persistently negative one means the clock-offset estimate has the wrong
    sign, and that is the single fault this module could not otherwise detect.
    The shared "-1 means unmeasured" convention then re-hid it — any consumer
    gating on `< 0` maps the fault onto the same em-dash as "handshake hasn't
    landed". frame_age_measured is what distinguishes them."""
    unmeasured = health.snapshot().event_fields()
    assert unmeasured["frame_age_ms"] == -1.0
    assert unmeasured["frame_age_measured"] is False

    health.note_frame_received(age_ms=-1.0)   # a real reading that IS -1.0
    measured = health.snapshot().event_fields()
    assert measured["frame_age_ms"] == -1.0   # identical to the sentinel...
    assert measured["frame_age_measured"] is True   # ...and only this tells them apart
