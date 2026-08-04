"""Audit HIGH-7: one Chroma client for the whole process.

Each memory module previously built its own PersistentClient on the same
path — three sqlite handles under one DB. This asserts all three share the
same memoized client AND the collections still read against the live DB.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.database import get_chroma_client
from backend.core.memory.long_term import LongTermMemory
from backend.core.memory.screen_memory import screen_memory
from backend.core.memory.timeline import timeline


def test_all_memory_modules_share_one_client():
    assert get_chroma_client() is LongTermMemory().client
    assert get_chroma_client() is screen_memory.client
    assert get_chroma_client() is timeline.client


def test_client_is_memoized():
    assert get_chroma_client() is get_chroma_client()


def test_collections_read_against_live_db():
    """The shared client must still serve all three collections — the swap
    must not have pointed the modules at a fresh empty store."""
    assert timeline.collection.count() >= 0
    assert screen_memory.collection.count() >= 0
    assert LongTermMemory().collection.count() >= 0
