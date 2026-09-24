"""Warming the local models must never be able to break or delay startup.

The first spoken command after a boot paid phi3's cold load — 6408ms measured
here against 861ms warm — and the first command is usually the one being
demonstrated. Nothing preloaded anything.

A warm-up that delays or crashes startup is worse than the cold start it
avoids, so the interesting behaviour is all in the failure paths.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.daemon import preload


def test_start_returns_immediately(monkeypatch):
    """Ollama can take seconds to load a model; startup must not wait."""
    released = threading.Event()
    monkeypatch.setattr(preload, "_warm", released.wait)

    t0 = time.perf_counter()
    preload.start()
    elapsed = (time.perf_counter() - t0) * 1000
    released.set()

    assert elapsed < 200, f"start() blocked for {elapsed:.0f}ms"


def test_a_dead_ollama_does_not_raise(monkeypatch):
    """Ollama being down is an expected outcome, not an error — the readiness
    probe is what reports it."""
    import backend.ai_modules.llm.ollama_client as oc

    def boom(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(oc, "generate_sync", boom)
    monkeypatch.setattr(oc, "embed", boom)

    preload._warm()   # must not raise


def _record_embedder(monkeypatch, sink):
    import backend.core.memory.embedding as emb

    monkeypatch.setattr(emb, "get_embedder",
                        lambda name: (lambda texts: sink.append(name) or [[0.1] * 384]))


def test_a_failed_chat_warmup_still_warms_the_embedder(monkeypatch):
    """One model missing must not skip the other — they are independent, and
    memory search needs its embedder whether or not phi3 loaded."""
    import backend.ai_modules.llm.ollama_client as oc

    embedded = []
    monkeypatch.setattr(oc, "generate_sync",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no phi3")))
    _record_embedder(monkeypatch, embedded)

    preload._warm()
    assert embedded, "embedder was skipped because the chat model failed"


def test_the_embedder_warms_without_ollama(monkeypatch):
    """Memory is local now; a laptop with no Ollama still gets a warm embedder."""
    import backend.ai_modules.llm.ollama_client as oc

    def boom(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(oc, "generate_sync", boom)
    embedded = []
    _record_embedder(monkeypatch, embedded)
    preload._warm()
    assert embedded


def test_it_warms_the_models_the_voice_path_actually_uses(monkeypatch):
    """Warming the wrong model is the same as not warming at all."""
    import backend.ai_modules.llm.ollama_client as oc
    from backend.server.config import settings

    asked = {}
    monkeypatch.setattr(oc, "generate_sync",
                        lambda *a, **k: asked.update(chat=k.get("model")) or "ok")
    embedded = []
    _record_embedder(monkeypatch, embedded)

    preload._warm()
    assert asked["chat"] == settings.fast_model
    assert embedded == [settings.memory_embedder]


def test_the_warmup_thread_cannot_outlive_the_process(monkeypatch):
    """A non-daemon thread blocked on a hung Ollama would hang shutdown."""
    started = threading.Event()
    seen = {}

    def capture():
        seen["daemon"] = threading.current_thread().daemon
        started.set()

    monkeypatch.setattr(preload, "_warm", capture)
    preload.start()
    assert started.wait(timeout=5), "warm-up thread never ran"
    assert seen["daemon"] is True
