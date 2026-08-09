"""Brain.recall must not re-rank what LongTermMemory already ranked.

LTM.search ranks candidates by
    semantic*0.4 + temporal*0.2 + importance*0.25 + confidence*0.15 + access_boost
Brain.recall then re-sorted them by `relevance * importance * confidence`.
`relevance` is a stored constant (1.0 for every entry the writers create), so
that key is really importance*confidence — semantic similarity and recency,
the two signals that make retrieval relevant to the *query*, were discarded.
A stale off-topic memory with importance 0.9 outranked the exact answer.

MemoryManager.recall already carried this fix; Brain.recall was the stale copy,
and so were Brain.forget and Brain.strengthen_memory. Brain now delegates
instead of duplicating, so these stub only `ltm` on the real manager — that
way the assertion covers the whole chain (Brain -> MemoryManager.recall ->
ltm.search) and a broken delegation fails here rather than passing against a
hand-built stand-in.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.memory.base import MemoryEntry, MemoryType


def _entry(content: str, importance: float, confidence: float) -> MemoryEntry:
    return MemoryEntry(content=content, mtype=MemoryType.FACT,
                       importance=importance, confidence=confidence)


def test_recall_preserves_ltm_ordering(monkeypatch):
    from backend.core import brain as brain_mod

    # best_match ranks first in LTM (strong semantic hit) but loses every
    # importance*confidence tiebreak — exactly the case the old sort inverted.
    best_match = _entry("garage door code is 4417", importance=0.3, confidence=0.6)
    off_topic = _entry("user prefers dark mode", importance=0.9, confidence=1.0)
    seen = {}

    def fake_search(query, mtype=None, limit=5, min_importance=0.0, **kw):
        seen.update(query=query, limit=limit, min_importance=min_importance)
        return [best_match, off_topic]

    from backend.core.memory.manager import memory as memory_manager
    monkeypatch.setattr(memory_manager, "ltm", SimpleNamespace(search=fake_search))

    out = brain_mod.Brain().recall("what is the garage code", limit=2, min_importance=0.2)

    assert [e.content for e in out] == [best_match.content, off_topic.content]
    # min_importance is LTM's job — it filters before truncating to `limit`,
    # so filtering after an over-fetch here is both redundant and lossier.
    assert seen == {"query": "what is the garage code", "limit": 2, "min_importance": 0.2}


def test_recall_marks_entries_accessed(monkeypatch):
    """Access tracking is the one side effect recall keeps (it feeds LTM's
    access_boost once the entry is written back)."""
    from backend.core import brain as brain_mod

    entry = _entry("a fact", importance=0.5, confidence=0.9)
    from backend.core.memory.manager import memory as memory_manager
    monkeypatch.setattr(memory_manager, "ltm",
                        SimpleNamespace(search=lambda *a, **kw: [entry]))

    brain_mod.Brain().recall("q")

    assert entry.access_count == 1
    assert entry.last_accessed is not None


def test_brain_delegates_forget_instead_of_returning_false(monkeypatch):
    """Brain.forget returned a hardcoded False with a "placeholder" comment.
    The audit recorded that as fixed — on MemoryManager.forget, not on this
    copy, so "forget that" silently did nothing through the Brain path."""
    from backend.core import brain as brain_mod
    from backend.core.memory.manager import memory as memory_manager

    deleted = []
    monkeypatch.setattr(memory_manager, "ltm",
                        SimpleNamespace(delete=lambda mid: deleted.append(mid) or True))

    assert brain_mod.Brain().forget("mem-123") is True
    assert deleted == ["mem-123"]


def test_brain_strengthen_does_not_re_add_an_existing_row(monkeypatch):
    """It called ltm.store(entry) on an entry that already has an id, and
    store() uses collection.add(), not upsert — so the strengthened importance
    was never persisted, and on a Chroma build tolerating duplicate ids it
    would have re-grown the rows T-memory-duplicate-rows purged."""
    from backend.core import brain as brain_mod
    from backend.core.memory.manager import memory as memory_manager

    entry = _entry("a fact", importance=0.5, confidence=0.9)
    entry.metadata["id"] = "mem-1"
    calls = {"store": 0, "strengthen": []}

    monkeypatch.setattr(memory_manager, "ltm", SimpleNamespace(
        search=lambda *a, **kw: [entry],
        store=lambda e: calls.__setitem__("store", calls["store"] + 1),
        strengthen_memory=lambda mid, amt: calls["strengthen"].append((mid, amt)),
    ))

    assert brain_mod.Brain().strengthen_memory("a fact", 0.2) == 1
    assert calls["store"] == 0, "strengthen re-added the row instead of updating it"
    assert calls["strengthen"] == [("mem-1", 0.2)]
