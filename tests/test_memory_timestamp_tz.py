"""Timezone-naive timestamps in the memory store.

Everything in Chroma was written by `datetime.now()` (naive local). The age
subtractions in long_term/timeline/screen_memory all sit inside `except` blocks
that swallow and return [] — so ONE aware timestamp entering the store does not
raise, it silently empties semantic recall. Several backend modules
(dogfooding, data_sources, ws_ui) do produce `datetime.now(timezone.utc)`, so
"nobody passes an aware datetime" was luck, not a guarantee.

The fix normalizes at the boundary (base.naive_local / base.parse_ts) instead
of migrating every existing row to aware UTC.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.core.memory.base import MemoryEntry, MemoryType, naive_local, parse_ts


def test_naive_local_leaves_naive_alone():
    dt = datetime(2026, 8, 13, 9, 30)
    assert naive_local(dt) is dt


def test_naive_local_converts_aware_to_the_same_instant():
    aware = datetime.now(timezone.utc)
    got = naive_local(aware)
    assert got.tzinfo is None
    # Same instant, expressed in local time — not a bare tzinfo strip, which
    # would shift the memory by the UTC offset and mis-age every entry.
    assert abs(got - aware.astimezone().replace(tzinfo=None)) < timedelta(seconds=1)


def test_parse_ts_accepts_both_strings_and_datetimes():
    assert parse_ts("2026-08-13T09:30:00") == datetime(2026, 8, 13, 9, 30)
    assert parse_ts(datetime(2026, 8, 13, 9, 30)) == datetime(2026, 8, 13, 9, 30)
    assert parse_ts("2026-08-13T09:30:00+00:00").tzinfo is None


def test_an_aware_entry_can_still_be_aged():
    """The failure this guards: `datetime.now() - entry.timestamp` raising
    TypeError inside an except block, so recall returns [] with no error."""
    entry = MemoryEntry(content="written with an aware clock",
                        mtype=MemoryType.FACT,
                        timestamp=datetime.now(timezone.utc))
    round_tripped = MemoryEntry.from_dict(entry.to_dict())
    assert round_tripped.timestamp.tzinfo is None
    age = datetime.now() - round_tripped.timestamp  # would raise before the fix
    assert age < timedelta(minutes=5)


def test_round_trip_preserves_a_naive_entry_exactly():
    entry = MemoryEntry(content="ordinary", mtype=MemoryType.FACT,
                        timestamp=datetime(2026, 8, 13, 9, 30))
    entry.last_accessed = datetime(2026, 8, 13, 10, 0)
    back = MemoryEntry.from_dict(entry.to_dict())
    assert back.timestamp == entry.timestamp
    assert back.last_accessed == entry.last_accessed


def test_from_dict_keeps_an_absent_last_accessed_as_none():
    """last_accessed is Optional; the parse must not turn None into a crash or
    an epoch date."""
    entry = MemoryEntry(content="never read", mtype=MemoryType.FACT)
    assert entry.last_accessed is None
    assert MemoryEntry.from_dict(entry.to_dict()).last_accessed is None


def test_mixed_aware_and_naive_entries_still_sort():
    """MemoryManager sorts recent events by timestamp; a mixed list raises
    TypeError on comparison exactly like the subtraction does."""
    entries = [
        MemoryEntry(content="aware", mtype=MemoryType.EVENT, timestamp=datetime.now(timezone.utc)),
        MemoryEntry(content="naive", mtype=MemoryType.EVENT, timestamp=datetime.now()),
    ]
    with pytest.raises(TypeError):
        sorted(entries, key=lambda e: e.timestamp)          # the bug
    assert len(sorted(entries, key=lambda e: naive_local(e.timestamp))) == 2   # the fix
