"""MemoryHitEvent has to fire on the turn path, not just from the HTTP route.

Before this, the only publisher was GET /memory/search — a route nothing in the
voice or chat pipeline calls. ContextBuilder ran an LTM search on every single
turn and published nothing, so the UI's Memory Engine readout was permanently
empty no matter how much the assistant actually recalled.

Covers: the publish fires from the turn path, carries the score breakdown,
survives the serializer that puts it on the wire, and never costs the caller
its context when telemetry fails.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.memory.base import MemoryEntry, MemoryType
from backend.daemon.ui_events import MemoryHitEvent


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event, priority=None):
        self.published.append(event)


def _entry(content: str, source: str = "user") -> MemoryEntry:
    return MemoryEntry(
        content=content,
        mtype=MemoryType.FACT,
        timestamp=datetime.now(),
        metadata={"id": "x"},
        source=source,
    )


def _candidates():
    return [
        {"entry": _entry("user prefers dark mode", "user"), "combined_score": 0.8123},
        {"entry": _entry("standup is at 9am", "notes"), "combined_score": 0.4567},
    ]


def _fake_memory_manager(candidates=None, count=42, raises=None):
    mm = MagicMock()
    if raises is not None:
        mm.ltm.search_scored.side_effect = raises
    else:
        mm.ltm.search_scored.return_value = (
            _candidates() if candidates is None else candidates
        )
    mm.ltm.count.return_value = count
    mm.ltm.collection.name = "sg_cube_memories"
    return mm


def _collect_ltm(memory_manager, bus):
    """Run the turn-path LTM read with the bus and store swapped out."""
    from backend.core.context import builder

    with patch.object(builder, "memory_manager", memory_manager), \
         patch.object(builder, "get_bus", return_value=bus):
        return builder.context_builder._get_ltm_context("what do you know about me")


# ── The event fires at all ─────────────────────────────────────────────

def test_turn_path_ltm_read_publishes_memory_hit():
    bus = _FakeBus()
    _collect_ltm(_fake_memory_manager(), bus)

    events = [e for e in bus.published if isinstance(e, MemoryHitEvent)]
    assert len(events) == 1, "ContextBuilder must publish exactly one MemoryHitEvent"


def test_event_carries_the_fields_the_panel_reads():
    bus = _FakeBus()
    _collect_ltm(_fake_memory_manager(), bus)
    ev = bus.published[0]

    assert ev.query == "what do you know about me"
    assert ev.results_count == 2
    assert ev.collection == "sg_cube_memories"
    assert ev.total_entries == 42
    assert [h.title for h in ev.hits] == [
        "user prefers dark mode",
        "standup is at 9am",
    ]
    assert [h.source for h in ev.hits] == ["user", "notes"]
    # Scores come from the same pass that ranked them — no second search.
    assert ev.hits[0].score == pytest.approx(0.812)
    assert ev.hits[1].score == pytest.approx(0.457)


def test_empty_recall_still_publishes_with_zero_count():
    """A miss is information: the panel shows "no matches", not a stale hit."""
    bus = _FakeBus()
    _collect_ltm(_fake_memory_manager(candidates=[]), bus)

    assert len(bus.published) == 1
    assert bus.published[0].results_count == 0
    assert bus.published[0].hits == []


# ── The caller still gets its context ──────────────────────────────────

def test_returns_entries_not_scored_candidates():
    """Downstream agents consume MemoryEntry objects; the refactor must not
    leak the {entry, scores} wrapper into AgentContext.long_term_memory."""
    bus = _FakeBus()
    result = _collect_ltm(_fake_memory_manager(), bus)

    assert all(isinstance(e, MemoryEntry) for e in result)
    assert [e.content for e in result] == [
        "user prefers dark mode",
        "standup is at 9am",
    ]


def test_publish_failure_does_not_cost_the_caller_its_context():
    class _BrokenBus:
        def publish(self, event, priority=None):
            raise RuntimeError("bus down")

    result = _collect_ltm(_fake_memory_manager(), _BrokenBus())
    assert len(result) == 2, "telemetry failure must not empty the context"


def test_search_failure_publishes_nothing_and_returns_empty():
    bus = _FakeBus()
    result = _collect_ltm(_fake_memory_manager(raises=RuntimeError("chroma down")), bus)

    assert result == []
    assert bus.published == [], "no event when there was no search"


# ── The refactored LTM search keeps its old contract ───────────────────

def test_search_returns_plain_entries_via_search_scored():
    from backend.core.memory.long_term import LongTermMemory

    class _StubLTM:
        search = LongTermMemory.search

        def search_scored(self, query, mtype=None, limit=5, use_rerank=True,
                          min_importance=0.0):
            self.seen = (query, limit, use_rerank, min_importance)
            return _candidates()

    stub = _StubLTM()
    entries = stub.search("dark mode", limit=3)

    assert [e.content for e in entries] == [
        "user prefers dark mode",
        "standup is at 9am",
    ]
    assert stub.seen == ("dark mode", 3, True, 0.0), "args must pass through"


# ── The wire seam ──────────────────────────────────────────────────────

def test_event_survives_the_websocket_serializer():
    """Nested MemoryHit dataclasses must come out as JSON the browser can read
    — a TypeError here kills the whole broadcast, not just this event."""
    from backend.server.ws_ui import TYPE_MAP, UIEventManager

    bus = _FakeBus()
    _collect_ltm(_fake_memory_manager(), bus)

    assert TYPE_MAP[MemoryHitEvent] == "memory_hit"
    payload = UIEventManager()._serialize(bus.published[0])
    decoded = json.loads(json.dumps(payload))

    assert decoded["results_count"] == 2
    assert decoded["collection"] == "sg_cube_memories"
    assert decoded["total_entries"] == 42
    assert decoded["hits"][0]["title"] == "user prefers dark mode"
    assert isinstance(decoded["hits"][0]["score"], float)
