"""Offline CPU Whisper must decode one capture at a time.

`_cpu_lock` guarded model CONSTRUCTION only — the double-checked load — and
`_cpu_model.transcribe(...)` ran unlocked. Turn bodies are serialized by
`wake_word._start_turn`, but only up to `_TURN_HANDOVER_TIMEOUT_S`; past that
two (here, three) turn bodies run at once, each on its own thread, and each
calls into this one CPU model. Observed in a live log:

    [wake] previous turn still running after 15s; starting anyway
    [wake] previous turn still running after 15s; starting anyway
    STT: answered offline on CPU in 19120ms

against 2995ms for the same model earlier in the same session.

The timing is a single sample and is NOT what this test asserts — the
structural fact is enough on its own: one CTranslate2 model, configured for all
cores, entered concurrently by N threads that then fight over those cores.

The subtle part, and the reason the obvious one-line fix is wrong:
`WhisperModel.transcribe()` returns a LAZY generator. Almost none of the work
happens in that call — decoding happens while `_collect_segments` iterates it.
A lock around the `transcribe()` call alone would serialize the setup and leave
every bit of the actual inference running concurrently, while looking correct.
So the lock has to be held across the iteration too.
"""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import stt_whisper


class _ConcurrencyProbe:
    """Stands in for the loaded CPU model and records overlap.

    Counts occupancy separately for the transcribe() call and for the
    generator's iteration, because only the second one is the real work.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.inside = 0
        self.max_concurrent_setup = 0
        self.max_concurrent_decode = 0

    def _enter(self, which):
        with self._lock:
            self.inside += 1
            attr = f"max_concurrent_{which}"
            setattr(self, attr, max(getattr(self, attr), self.inside))

    def _exit(self):
        with self._lock:
            self.inside -= 1

    def transcribe(self, audio, **_kw):
        self._enter("setup")
        try:
            # Long enough that unserialized callers reliably overlap here.
            threading.Event().wait(0.05)
        finally:
            self._exit()

        def _segments():
            # THE REAL WORK. faster-whisper decodes during iteration, not in
            # the transcribe() call above.
            self._enter("decode")
            try:
                threading.Event().wait(0.05)
                yield SimpleNamespace(text="hello", no_speech_prob=0.1,
                                      avg_logprob=-0.3)
            finally:
                self._exit()

        info = SimpleNamespace(language="en", language_probability=1.0,
                               duration=1.0)
        return _segments(), info


def _run_concurrently(n=4):
    probe = _ConcurrencyProbe()
    audio = np.zeros(16000, dtype=np.float32)
    errors = []

    def _call():
        try:
            stt_whisper.transcribe_array_cpu(audio, 16000)
        except BaseException as e:      # noqa: BLE001 - recording it IS the test
            errors.append(f"{type(e).__name__}: {e}")

    with patch.object(stt_whisper, "_cpu_model", probe):
        threads = [threading.Thread(target=_call) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

    assert not errors, errors
    return probe


def test_decoding_is_serialized():
    """The one that matters. Overlap here is what turned 2995ms into 19120ms."""
    probe = _run_concurrently()
    assert probe.max_concurrent_decode == 1, (
        f"{probe.max_concurrent_decode} threads decoded through the one CPU "
        "model at once — they contend for the same cores, and each turn gets "
        "slower in proportion"
    )


def test_the_lock_covers_the_lazy_generator_not_just_the_call():
    """Guard against the plausible-looking wrong fix.

    Locking only `_cpu_model.transcribe(...)` serializes the setup and leaves
    the decode concurrent. That would make the assertion above fail while the
    diff reads like a correct fix, so state it explicitly: if setup is
    serialized, decode must be too.
    """
    probe = _run_concurrently()
    assert probe.max_concurrent_setup == 1, probe.max_concurrent_setup
    assert probe.max_concurrent_decode == 1, (
        "setup is serialized but decoding is not — the lock is around the "
        "transcribe() call and not around iterating its generator, which is "
        "where faster-whisper does the work"
    )


def test_a_transcript_still_comes_back():
    """Serializing must not change the answer."""
    probe = _ConcurrencyProbe()
    audio = np.zeros(16000, dtype=np.float32)
    with patch.object(stt_whisper, "_cpu_model", probe):
        out = stt_whisper.transcribe_array_cpu(audio, 16000)
    assert out["text"] == "hello", out


def test_the_lock_is_released_when_decoding_raises():
    """A model that throws mid-decode must not wedge every later capture —
    that would turn one bad frame into a permanently deaf offline path."""
    audio = np.zeros(16000, dtype=np.float32)

    class _Boom:
        def transcribe(self, _audio, **_kw):
            def _segments():
                raise RuntimeError("decode exploded")
                yield  # pragma: no cover - generator marker
            info = SimpleNamespace(language="en", language_probability=1.0,
                                   duration=1.0)
            return _segments(), info

    with patch.object(stt_whisper, "_cpu_model", _Boom()):
        try:
            stt_whisper.transcribe_array_cpu(audio, 16000)
        except RuntimeError:
            pass

    assert not stt_whisper._cpu_lock.locked(), (
        "the CPU model lock survived an exception; every later offline "
        "transcription would block forever"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
