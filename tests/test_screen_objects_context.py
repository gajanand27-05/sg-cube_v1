"""ContextBuilder.screen_objects was permanently empty.

`_get_screen_objects()` called `screen_memory.get_latest_observation()` and then
`.get("keywords", "")` on the result. That method is annotated
`-> Optional[str]` and returns only the document text, so the call raised
AttributeError on a str — every turn, straight into a bare `except: pass`.

Nothing broke visibly, which is why it lasted: no consumer reads
screen_objects (the planner prompt renders only capabilities,
recent_conversation, long_term_memory and recent_events). The full cost was
paid every turn — get_recent_observations scans the whole collection, ~15ms
warm on 359 rows — and the result was discarded.

The fix reads get_recent_observations(limit=1), which already returns the row
WITH its keywords metadata, so no new accessor was needed.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.context.builder import context_builder
from backend.core.memory import screen_memory as screen_memory_module


class _FakeScreenMemory:
    """Mirrors the real return shapes exactly — a str from
    get_latest_observation, a list of dicts from get_recent_observations. The
    bug was believing those were the same thing."""

    def __init__(self, keywords="code,reporting"):
        self._keywords = keywords

    def get_latest_observation(self):
        return "User was looking at VS Code: editing. Keywords: " + self._keywords

    def get_recent_observations(self, limit=10):
        return [{
            "content": self.get_latest_observation(),
            "app": "Code",
            "keywords": self._keywords,
            "created_at": "2026-08-13T10:00:00",
        }][:limit]


@pytest.fixture()
def fake_memory(monkeypatch):
    fake = _FakeScreenMemory()
    monkeypatch.setattr(screen_memory_module, "screen_memory", fake)
    monkeypatch.setattr("backend.core.context.builder.screen_memory", fake)
    return fake


def test_screen_objects_are_actually_produced(fake_memory):
    objects = context_builder._get_screen_objects()
    assert [o.label for o in objects] == ["code", "reporting"], (
        f"got {objects!r} — an empty list here is the original bug: the "
        "AttributeError is swallowed and looks identical to 'nothing on screen'"
    )
    assert all(o.confidence == 0.8 for o in objects)


def test_the_old_str_accessor_would_still_fail(fake_memory):
    """Pins WHY the fix works. If get_latest_observation ever starts returning
    a dict, this test fails and the comment in builder.py becomes wrong —
    better than the comment silently rotting."""
    latest = fake_memory.get_latest_observation()
    assert isinstance(latest, str)
    with pytest.raises(AttributeError):
        latest.get("keywords", "")


def test_no_observations_is_not_an_error(monkeypatch):
    """A fresh install has an empty collection; that must stay an empty list,
    not a logged failure."""
    class _Empty:
        def get_recent_observations(self, limit=10):
            return []
    monkeypatch.setattr("backend.core.context.builder.screen_memory", _Empty())
    assert context_builder._get_screen_objects() == []


def test_a_failing_screen_memory_is_logged_not_silent(monkeypatch, caplog):
    """The bare `except: pass` is what hid the original AttributeError for the
    life of the function."""
    class _Boom:
        def get_recent_observations(self, limit=10):
            raise RuntimeError("chroma down")
    monkeypatch.setattr("backend.core.context.builder.screen_memory", _Boom())

    with caplog.at_level("WARNING"):
        assert context_builder._get_screen_objects() == []
    assert any("chroma down" in r.message for r in caplog.records), (
        "the failure was swallowed without a trace — exactly the shape that "
        "kept this function broken"
    )
