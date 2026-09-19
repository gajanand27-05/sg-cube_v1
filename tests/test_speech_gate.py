"""The post-wake speech gate must be conservative and must fail open.

Measured on the archived captures it drops 9 of 41, of which 8 were empty
transcripts and the 9th was an ASR hallucination that had reached the router.
No real command was dropped. These tests pin the properties that make that
safe, so a later "improvement" to the threshold cannot quietly start eating
commands.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import speech_gate


@pytest.fixture(autouse=True)
def _reset_module_state():
    """The loader memoises; a failed load latches. Reset between tests."""
    speech_gate._model = None
    speech_gate._load_failed = False
    yield
    speech_gate._model = None
    speech_gate._load_failed = False


def test_fails_open_when_silero_is_unavailable(monkeypatch):
    """A broken VAD must never be able to mute the assistant."""
    monkeypatch.setattr(speech_gate, "_get_model", lambda: None)
    keep, secs = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is True
    assert secs is None, "unavailable must be None, not 0.0 — they mean different things"


def test_fails_open_when_silero_raises_mid_call(monkeypatch):
    """A model that loads but explodes on use is the same situation."""
    class _Boom:
        def __call__(self, *a, **k):
            raise RuntimeError("boom")

    # Patch only the MODEL. The real speech_seconds must be the code under
    # test — it owns the try/except that turns a mid-call explosion into a
    # pass-through.
    monkeypatch.setattr(speech_gate, "_get_model", lambda: _Boom())
    keep, secs = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is True
    assert secs is None


def test_zero_speech_is_dropped(monkeypatch):
    monkeypatch.setattr(speech_gate, "speech_seconds", lambda *a, **k: 0.0)
    keep, secs = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is False
    assert secs == 0.0


def test_any_speech_at_all_is_kept(monkeypatch):
    """0.40s is the real 'Onyx open notepad' — less speech than most noise
    clips, which is exactly why the threshold is zero and not a ratio."""
    monkeypatch.setattr(speech_gate, "speech_seconds", lambda *a, **k: 0.40)
    keep, _ = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is True

    monkeypatch.setattr(speech_gate, "speech_seconds", lambda *a, **k: 0.01)
    keep, _ = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is True, "a hair of speech is still speech"


def test_gate_can_be_switched_off(monkeypatch):
    from backend.server.config import settings

    monkeypatch.setattr(settings, "enable_speech_gate", False)
    monkeypatch.setattr(speech_gate, "speech_seconds",
                        lambda *a, **k: pytest.fail("must not run when disabled"))
    keep, secs = speech_gate.has_speech(np.zeros(16000, dtype=np.float32))
    assert keep is True and secs is None


def test_silence_really_scores_zero_on_the_real_model():
    """End-to-end against silero itself, not a stub — the stubs above would
    all pass against a model that scored everything as speech."""
    if speech_gate._get_model() is None:
        pytest.skip("silero-vad unavailable in this environment")
    secs = speech_gate.speech_seconds(np.zeros(16000 * 2, dtype=np.float32))
    assert secs == 0.0


def test_empty_audio_is_not_an_error():
    if speech_gate._get_model() is None:
        pytest.skip("silero-vad unavailable in this environment")
    assert speech_gate.speech_seconds(np.zeros(0, dtype=np.float32)) == 0.0
