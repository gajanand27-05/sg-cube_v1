"""Audit MED-4: manager.forget() was a hardcoded `return False` placeholder.

Now delegates to LongTermMemory.delete — a real Chroma hard-delete with a
truthful return value. This test stubs the collection so the suite stays
offline and doesn't touch the live vector DB (object.__new__ skips the
constructor, which would open PersistentClient).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.memory.long_term import LongTermMemory
from backend.core.memory.manager import MemoryManager


def _stub_ltm(existing: list[str]) -> tuple[LongTermMemory, MagicMock]:
    col = MagicMock()
    col.get.return_value = {"ids": existing}
    ltm = object.__new__(LongTermMemory)
    ltm.collection = col
    return ltm, col


def _manager_with(ltm: LongTermMemory) -> MemoryManager:
    manager = object.__new__(MemoryManager)
    manager.ltm = ltm
    return manager


def test_delete_calls_chroma_with_the_id():
    ltm, col = _stub_ltm(["mem-1"])
    manager = _manager_with(ltm)

    assert manager.forget("mem-1") is True
    col.get.assert_called_once_with(ids=["mem-1"], include=[])
    col.delete.assert_called_once_with(ids=["mem-1"])
    assert ltm.count() == 1  # real LongTermMemory.delete drove the stub


def test_delete_unknown_id_returns_false_and_skips_delete():
    ltm, col = _stub_ltm([])
    manager = _manager_with(ltm)

    assert manager.forget("missing") is False
    col.delete.assert_not_called()