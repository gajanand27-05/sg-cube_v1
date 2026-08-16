"""Work that is not the user's answer must not be on the user's clock.

Two things were, both found by measuring a real turn rather than reading code.

1. The episodic summarizer fires a second LLM call after every tool-using
   turn. It is fire-and-forget, so it does not delay the reply it follows —
   but it does not finish before the NEXT turn either, and it competes with
   that turn for the same provider. Measured over sequential tool turns:
   14535ms median with it live, 6539ms with it stubbed. ~8s per turn, paid by
   the turn after.

   It was also not buying anything. The model returns patterns as objects,
   Chroma rejects a non-string document, and every extraction was discarded
   after the call had already been paid for:

       Failed to store semantic memory: Expected document to be a str, got
       {'workflow_name': '...', 'steps': [...], 'tools': ['duckduckgo']}

2. _log_to_db writes a Supabase row inline, before process_input returns —
   248ms median, 1335ms worst, on every turn, for a telemetry row nothing
   reads synchronously.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── the summarizer is off by default, and skips cheaply ────────────────

def test_it_is_off_by_default():
    """8s a turn is a steep price for a feature whose value is unmeasured."""
    from backend.server.config import settings
    assert settings.enable_episodic_summarizer is False


def test_disabled_means_no_llm_call_at_all():
    """Off has to mean off. Building the prompt and then bailing would still
    pay the context work."""
    import asyncio
    from backend.core.memory.episodic import summarizer
    from backend.server.config import settings

    called = []

    def _provider():
        called.append(1)
        raise AssertionError("the provider must not be reached when disabled")

    orig = settings.enable_episodic_summarizer
    try:
        settings.enable_episodic_summarizer = False
        with patch("backend.core.memory.episodic.get_provider", _provider):
            asyncio.run(summarizer.summarize_and_store("q", [{"tool": "x"}]))
    finally:
        settings.enable_episodic_summarizer = orig
    assert not called


def test_no_interactions_still_short_circuits():
    import asyncio
    from backend.core.memory.episodic import summarizer

    with patch("backend.core.memory.episodic.get_provider") as p:
        asyncio.run(summarizer.summarize_and_store("q", []))
    assert not p.called


# ── the coercion that made its output storable ─────────────────────────

def test_the_real_dict_shape_becomes_a_string():
    """Verbatim from the live failure."""
    from backend.core.memory.episodic import _as_text

    observed = {
        "workflow_name": "search and answer for current time",
        "steps": ["User initiates query", "DuckDuckGo is used"],
        "tools": ["duckduckgo"],
    }
    out = _as_text(observed)
    assert isinstance(out, str) and out
    assert "search and answer for current time" in out


def test_a_readable_field_is_preferred_over_json():
    from backend.core.memory.episodic import _as_text
    assert _as_text({"workflow": "User asked the time"}) == "User asked the time"
    assert _as_text({"description": "did a thing"}) == "did a thing"


def test_plain_strings_pass_through():
    from backend.core.memory.episodic import _as_text
    assert _as_text("  User likes dark mode  ") == "User likes dark mode"


def test_nothing_returns_a_non_string():
    """Chroma rejects any non-str document, so this must hold for every shape
    the model can produce — that rejection is what silently binned the work."""
    from backend.core.memory.episodic import _as_text
    for item in ["a", {"x": 1}, ["a", "b"], 42, None, {"steps": ["s"]}, ()]:
        assert isinstance(_as_text(item), str), repr(item)


# ── command logging is off the response path ───────────────────────────

def test_log_to_db_does_not_block_the_caller():
    """It must hand off, not wait. A slow Supabase must cost the user nothing."""
    import threading
    import time
    from backend.core.orchestrator import router

    started = threading.Event()
    release = threading.Event()

    class _Slow:
        def table(self, _n):
            return self

        def insert(self, _p):
            return self

        def execute(self):
            started.set()
            release.wait(5)

    t0 = time.perf_counter()
    with patch.object(router, "get_service_client", lambda: _Slow()):
        router._log_to_db("u", "hello", None, "rule", "success", 1)
        elapsed = (time.perf_counter() - t0) * 1000
        assert started.wait(3), "the write never ran"
        release.set()

    assert elapsed < 250, (
        f"_log_to_db blocked the caller for {elapsed:.0f}ms; it is telemetry "
        "and belongs off the response path"
    )


def test_a_failing_log_never_raises():
    from backend.core.orchestrator import router

    def _boom():
        raise RuntimeError("supabase down")

    with patch.object(router, "get_service_client", _boom):
        router._log_to_db("u", "hello", None, "rule", "success", 1)  # must not raise


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
