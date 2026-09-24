"""Audit: three process-lifetime singletons were built with an unguarded
`if _x is None: _x = build()`. Two threads both see None, both build, and the
loser's object is silently discarded — for get_bus() the loser keeps a handle to
an orphan bus whose subscribers never see the winner's events.

Each test replaces the real constructor with a deliberately slow stub and counts
constructions across N threads. The delay makes the interleaving deterministic:
without double-checked locking every thread enters the body, so the count equals
the thread count. All three tests fail against the pre-fix code.
"""
import sys
import threading
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_THREADS = 8


def _hammer(fn) -> list:
    """Call fn() from _THREADS threads released together; return the results."""
    out: list = []
    out_lock = threading.Lock()
    ready = threading.Barrier(_THREADS)

    def worker():
        ready.wait()
        r = fn()
        with out_lock:
            out.append(r)

    threads = [threading.Thread(target=worker) for _ in range(_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return out


def test_get_bus_builds_exactly_one_bus():
    from backend.core import events

    built = []
    built_lock = threading.Lock()
    real_cls = events.AsyncEventBus

    class SlowBus(real_cls):
        def __init__(self, *a, **kw):
            time.sleep(0.05)  # widen the window every thread would race through
            super().__init__(*a, **kw)
            with built_lock:
                built.append(self)

    saved_bus, saved_init = events.bus, events._initialized
    events.AsyncEventBus = SlowBus
    events.bus = None
    try:
        results = _hammer(events.get_bus)
    finally:
        events.AsyncEventBus = real_cls
        events.bus, events._initialized = saved_bus, saved_init

    assert len(built) == 1, f"get_bus() constructed {len(built)} buses"
    assert len({id(r) for r in results}) == 1, "threads got different bus objects"


def test_speech_gate_vad_loads_once():
    import faster_whisper.vad as fw_vad

    from backend.ai_modules.speech import speech_gate

    calls = []
    calls_lock = threading.Lock()
    real_load = fw_vad.get_vad_model

    def slow_load():
        time.sleep(0.05)
        with calls_lock:
            calls.append(1)
        return "model-sentinel"

    saved = speech_gate._model, speech_gate._load_failed
    fw_vad.get_vad_model = slow_load
    speech_gate._model, speech_gate._load_failed = None, False
    try:
        results = _hammer(speech_gate._get_model)
    finally:
        fw_vad.get_vad_model = real_load
        speech_gate._model, speech_gate._load_failed = saved

    assert len(calls) == 1, f"get_vad_model ran {len(calls)} times"
    assert results == ["model-sentinel"] * _THREADS


def test_piper_voice_loads_once():
    from backend.ai_modules.speech import tts_piper

    calls = []
    calls_lock = threading.Lock()
    real_cls = tts_piper.PiperVoice

    class SlowVoice:
        @staticmethod
        def load(*a, **kw):
            time.sleep(0.05)
            with calls_lock:
                calls.append(1)
            return "voice-sentinel"

    saved = tts_piper._voice
    tts_piper.PiperVoice = SlowVoice
    tts_piper._voice = None
    try:
        results = _hammer(tts_piper._get_voice)
    finally:
        tts_piper.PiperVoice = real_cls
        tts_piper._voice = saved

    assert len(calls) == 1, f"PiperVoice.load ran {len(calls)} times"
    assert results == ["voice-sentinel"] * _THREADS
