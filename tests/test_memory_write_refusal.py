"""An unembeddable memory must be refused, not stored — T-memory-zero-vectors.

All three collections used to catch an embed failure, log it, append
`[0.0] * 768`, and store the row anyway. A zero vector has no direction, so
cosine distance to it is degenerate and the row can never rank. store() then
logged "Stored semantic memory" and count() grew, so nothing downstream — the
Memory Engine panel included — could tell. With local Ollama down for a day,
32 of 37 long-term rows ended up unsearchable.

These tests never touch the real database.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.memory.embedding import (
    EMBEDDING_DIM,
    EmbeddingUnavailable,
    ProviderEmbeddingFunction,
)


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event, priority=None):
        self.published.append(event)


def _provider(embed):
    p = MagicMock()
    p.embed = embed
    return p


GOOD_VECTOR = [0.1] * EMBEDDING_DIM


# ── The embedding function itself ───────────────────────────────────────

def test_healthy_embedding_passes_through():
    # Chroma wraps EmbeddingFunction.__call__ and normalises the result to
    # numpy, so compare numerically rather than by list identity.
    import numpy as np

    ef = ProviderEmbeddingFunction("test")
    with patch("backend.core.memory.embedding.get_provider",
               return_value=_provider(lambda t: GOOD_VECTOR)):
        out = ef(["hello"])
    assert len(out) == 1
    assert np.allclose(np.asarray(out[0], dtype=float), GOOD_VECTOR)


def test_backend_error_raises_instead_of_returning_zeros():
    """The regression. This used to return [[0.0]*768]."""
    def boom(text):
        raise ConnectionRefusedError("[WinError 10061] target machine refused it")

    ef = ProviderEmbeddingFunction("sg_cube_memories")
    with patch("backend.core.memory.embedding.get_provider", return_value=_provider(boom)):
        with pytest.raises(EmbeddingUnavailable) as exc:
            ef(["remember this"])

    assert "sg_cube_memories" in str(exc.value), "the error must name the collection"


@pytest.mark.parametrize("bad,label", [
    ([], "empty"),
    ([0.0] * EMBEDDING_DIM, "all-zero"),
    ([0.1] * 64, "wrong width"),
    (None, "none"),
])
def test_unusable_vectors_are_rejected(bad, label):
    """A backend that answers with junk is the same lost write by another route
    — an all-zero vector from the provider is exactly what we are stopping."""
    ef = ProviderEmbeddingFunction("test")
    with patch("backend.core.memory.embedding.get_provider",
               return_value=_provider(lambda t: bad)):
        with pytest.raises(EmbeddingUnavailable):
            ef(["something"])


def test_one_bad_document_fails_the_whole_batch():
    """Chroma writes a batch atomically; a partial embedding would silently
    poison whichever rows failed."""
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("dropped")
        return GOOD_VECTOR

    ef = ProviderEmbeddingFunction("test")
    with patch("backend.core.memory.embedding.get_provider", return_value=_provider(flaky)):
        with pytest.raises(EmbeddingUnavailable):
            ef(["first", "second", "third"])


# ── The write paths refuse, and say so ─────────────────────────────────

def _failing_collection():
    """A Chroma collection stand-in whose add() fails the way Chroma does when
    the embedding function raises."""
    coll = MagicMock()
    coll.add.side_effect = EmbeddingUnavailable("sg_cube_x: embedding backend unavailable")
    return coll


def test_long_term_store_refuses_and_reports():
    from backend.core.memory.base import MemoryEntry, MemoryType
    from backend.core.memory.long_term import LongTermMemory

    ltm = LongTermMemory.__new__(LongTermMemory)   # skip Chroma construction
    ltm.collection = _failing_collection()
    entry = MemoryEntry(content="user prefers dark mode", mtype=MemoryType.PREFERENCE,
                        metadata={})

    bus = _FakeBus()
    with patch("backend.core.events.get_bus", return_value=bus):
        stored = ltm.store(entry)

    assert stored is False, "store() must not report success for a refused write"
    assert len(bus.published) == 1
    event = bus.published[0]
    assert event.collection == "sg_cube_memories"
    assert "dark mode" in event.content_preview


def test_screen_memory_refuses_and_reports():
    from backend.core.memory.screen_memory import ScreenMemory

    sm = ScreenMemory.__new__(ScreenMemory)
    sm.collection = _failing_collection()

    bus = _FakeBus()
    with patch("backend.core.events.get_bus", return_value=bus):
        stored = sm.store_observation({"app": "VS Code", "summary": "editing",
                                       "keywords": ["python"]})

    assert stored is False
    assert bus.published[0].collection == "sg_cube_visual"


def test_timeline_refuses_and_reports():
    from backend.core.memory.timeline import TimelineMemory

    tl = TimelineMemory.__new__(TimelineMemory)
    tl.collection = _failing_collection()

    bus = _FakeBus()
    with patch("backend.core.events.get_bus", return_value=bus):
        stored = tl.record_event(content='User asked: "what time is it"', source="user_query")

    assert stored is False
    assert bus.published[0].collection == "sg_cube_timeline"


def test_successful_store_reports_true_and_publishes_nothing():
    from backend.core.memory.base import MemoryEntry, MemoryType
    from backend.core.memory.long_term import LongTermMemory

    ltm = LongTermMemory.__new__(LongTermMemory)
    ltm.collection = MagicMock()          # add() succeeds
    entry = MemoryEntry(content="standup is at nine", mtype=MemoryType.FACT, metadata={})

    bus = _FakeBus()
    with patch("backend.core.events.get_bus", return_value=bus):
        assert ltm.store(entry) is True
    assert bus.published == [], "a healthy write must not raise an alarm"


def test_a_non_embedding_storage_error_is_not_reported_as_a_write_failure():
    """Disk full or a Chroma internal error is a different fault and should not
    masquerade as 'the embedding backend is down'."""
    from backend.core.memory.base import MemoryEntry, MemoryType
    from backend.core.memory.long_term import LongTermMemory

    ltm = LongTermMemory.__new__(LongTermMemory)
    ltm.collection = MagicMock()
    ltm.collection.add.side_effect = OSError("disk full")
    entry = MemoryEntry(content="x", mtype=MemoryType.FACT, metadata={})

    bus = _FakeBus()
    with patch("backend.core.events.get_bus", return_value=bus):
        assert ltm.store(entry) is False
    assert bus.published == []


def test_telemetry_failure_does_not_break_the_write_path():
    from backend.core.memory.embedding import report_write_failure

    def explode(*a, **kw):
        raise RuntimeError("bus down")

    with patch("backend.core.events.get_bus", side_effect=explode):
        report_write_failure("sg_cube_memories", "unavailable", "content")  # must not raise


# ── Reads degrade to empty rather than to nonsense ─────────────────────

def test_search_returns_empty_when_embeddings_are_down():
    """Querying with a zero vector returned arbitrary nearest neighbours. An
    empty result is a shape every caller already handles."""
    from backend.core.memory.long_term import LongTermMemory

    ltm = LongTermMemory.__new__(LongTermMemory)
    ltm.collection = MagicMock()
    ltm.collection.query.side_effect = EmbeddingUnavailable("down")

    assert ltm.search_scored("anything") == []
    assert ltm.search("anything") == []
