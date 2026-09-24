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
    from backend.core import local_llm_health

    # Before warming anything: is the service even up? Every warm-up below
    # talks to local Ollama, and with it down they all "skip" into the log and
    # the first real symptom is the verifier rejecting commands — which sounds
    # to the user exactly like being misheard. Start it if we can.
    if not local_llm_health.ensure_running():
        line = local_llm_health.take_announcement()
        if line:
            try:
                # speak(), not speak_stream(): this thread has no running loop,
                # so speak() takes its asyncio.run branch and actually blocks
                # until the audio is out. Under a live loop it would be
                # fire-and-forget and silent — the trap trigger.py documents.
                from backend.ai_modules.speech import tts_piper

                tts_piper.speak(line)
            except Exception as e:
                log.warning("could not speak the local-models notice: %s", e)
        log.error("local models are offline; skipping the Ollama warm-ups")
        ollama_up = False
    else:
        ollama_up = True

    t0 = time.perf_counter()
    try:
        if not ollama_up:
            raise RuntimeError("local Ollama is not running")
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

    # Memory's embedder: local ONNX since 2026-09-25, so it warms whether or
    # not Ollama is up (it used to be nomic via Ollama, and skipped with it).
    t0 = time.perf_counter()
    try:
        from backend.core.memory.embedding import get_embedder

        get_embedder(settings.memory_embedder)(["ok"])
        log.info("preloaded memory embedder %s in %.1fs", settings.memory_embedder,
                 time.perf_counter() - t0)
    except Exception as e:
        log.info("preload of memory embedder %s skipped: %s", settings.memory_embedder, e)

    # The offline STT model, plus ONE decode on silence.
    #
    # Loading alone is not enough: measured, a cold first decode cost ~8s on
    # top of the 1.6s load, so the first command of an outage waited ~11s.
    # The warm-up pays that here, on a background thread at boot, where
    # nobody is listening. Costs ~292 MiB resident for a rare event — a
    # deliberate trade, gated by ENABLE_MODEL_PRELOAD like everything else here.
    t0 = time.perf_counter()
    try:
        import numpy as np

        from backend.ai_modules.speech import stt_whisper

        stt_whisper.transcribe_array_cpu(np.zeros(16000, dtype=np.float32), 16000)
        log.info("preloaded offline CPU STT (loaded + warmed) in %.1fs",
                 time.perf_counter() - t0)
    except Exception as e:
        log.info("preload of offline CPU STT skipped: %s", e)

    # Silero v5 (faster-whisper's ONNX copy), for the post-wake speech gate.
    # Measured 2026-09-24: ~590ms cold (import + load, 3 fresh processes),
    # then ~53ms mean per archived capture. The old torch-based silero was
    # 1518ms to load. Without this the load lands on the FIRST wake
    # of the session — the one turn where a delay is most obvious — and buys
    # nothing, since the gate only ever decides whether to skip work.
    t0 = time.perf_counter()
    try:
        from backend.ai_modules.speech import speech_gate

        if speech_gate._get_model() is not None:
            log.info("preloaded speech-gate VAD in %.1fs", time.perf_counter() - t0)
        else:
            log.info("preload of speech-gate VAD skipped: unavailable "
                     "(speech gate will pass every capture through)")
    except Exception as e:
        log.info("preload of speech-gate VAD skipped: %s", e)


def start() -> None:
    """Kick off the warm-up. Returns immediately."""
    threading.Thread(target=_warm, name="model-preload", daemon=True).start()
