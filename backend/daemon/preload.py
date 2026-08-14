"""Warm the models the first spoken command would otherwise wait on.

Every voice turn hits phi3 (intent classification, then verification) and
nomic (memory search). Warm they cost 861ms and ~50ms; cold, phi3 costs
6408ms — measured on this machine. Nothing preloaded them, so the first
command after every boot paid the cold price, and that first command is
usually the one being demonstrated.

Runs on a background thread and never raises: a warm-up that delays or breaks
startup is worse than the cold start it avoids. Ollama being down is an
expected outcome here, not an error — the readiness probe reports that.

ponytail: fire-and-forget with no retry. Ceiling — if Ollama starts *after*
the daemon, the warm-up has already missed and the first command pays cold
anyway. Upgrade path is a retry with backoff, which needs a shutdown signal to
avoid outliving the process.
"""
from __future__ import annotations

import logging
import threading
import time

from backend.server.config import settings

log = logging.getLogger(__name__)


def _warm() -> None:
    from backend.ai_modules.llm import ollama_client

    t0 = time.perf_counter()
    try:
        # A one-token reply: the point is to make Ollama load the weights, not
        # to get an answer. keep_alive is applied by the client, so the model
        # stays resident afterwards.
        ollama_client.generate_sync(
            "ok", model=settings.fast_model, temperature=0.0, timeout=120.0,
        )
        log.info("preloaded %s in %.1fs", settings.fast_model,
                 time.perf_counter() - t0)
    except Exception as e:
        log.info("preload of %s skipped: %s", settings.fast_model, e)

    t0 = time.perf_counter()
    try:
        ollama_client.embed("ok", model=settings.embedding_model)
        log.info("preloaded %s in %.1fs", settings.embedding_model,
                 time.perf_counter() - t0)
    except Exception as e:
        log.info("preload of %s skipped: %s", settings.embedding_model, e)


def start() -> None:
    """Kick off the warm-up. Returns immediately."""
    threading.Thread(target=_warm, name="model-preload", daemon=True).start()
