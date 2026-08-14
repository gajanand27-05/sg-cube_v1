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


def test_a_failed_chat_warmup_still_warms_the_embedder(monkeypatch):
    """One model missing must not skip the other — they are independent, and
    memory search needs nomic whether or not phi3 loaded."""
    import backend.ai_modules.llm.ollama_client as oc

    embedded = []
    monkeypatch.setattr(oc, "generate_sync",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no phi3")))
    monkeypatch.setattr(oc, "embed", lambda *a, **k: embedded.append(1) or [0.0])

    preload._warm()
    assert embedded, "embedder was skipped because the chat model failed"


def test_it_warms_the_models_the_voice_path_actually_uses(monkeypatch):
    """Warming the wrong model is the same as not warming at all."""
    import backend.ai_modules.llm.ollama_client as oc
    from backend.server.config import settings

    asked = {}
    monkeypatch.setattr(oc, "generate_sync",
                        lambda *a, **k: asked.update(chat=k.get("model")) or "ok")
    monkeypatch.setattr(oc, "embed",
                        lambda *a, **k: asked.update(embed=k.get("model")) or [0.0])

    preload._warm()
    assert asked["chat"] == settings.fast_model
    assert asked["embed"] == settings.embedding_model


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
