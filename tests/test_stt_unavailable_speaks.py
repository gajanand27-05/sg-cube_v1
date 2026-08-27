"""When STT cannot run, say so — differently per cause — and reach IDLE.

Silence is not acceptable and neither is one generic line. 59eb62f fixed
exactly this shape of bug: being interrupted and being misheard produced the
same sentence, so the user was told they had been misheard when they had not.
Piper is local and still works in every case here.
"""
import numpy as np
import pytest

from backend.ai_modules.speech.stt_gemini import SttUnavailable
from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import trigger


@pytest.fixture
def spoken(monkeypatch):
    said = []
    monkeypatch.setattr(trigger, "speak", lambda text, *a, **k: said.append(text))
    monkeypatch.setattr(trigger, "_play_chime", lambda: None)
    return said


def _raise(kind):
    def _f(audio, sample_rate=16000):
        raise SttUnavailable(kind, f"simulated {kind}")
    return _f


@pytest.mark.parametrize("kind,needle", [
    ("no_network", "network"),
    ("quota", "limit"),
    ("no_key", "key"),
])
def test_each_cause_speaks_its_own_line(monkeypatch, spoken, kind, needle):
    monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
    audio = (np.ones(16000, dtype=np.int16) * 4000).tobytes()

    trigger.handle_wake(audio)

    assert spoken, f"{kind} said nothing at all"
    assert needle in spoken[0].lower(), f"{kind} said {spoken[0]!r}"


def test_the_three_lines_are_distinct(monkeypatch):
    """If two causes share a sentence, the user cannot tell them apart —
    which is the bug 59eb62f fixed, reintroduced."""
    lines = set()
    for kind in ("no_network", "quota", "no_key"):
        said = []
        monkeypatch.setattr(trigger, "speak", lambda t, *a, **k: said.append(t))
        monkeypatch.setattr(trigger, "_play_chime", lambda: None)
        monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
        trigger.handle_wake((np.ones(16000, dtype=np.int16) * 4000).tobytes())
        lines.add(said[0])
    assert len(lines) == 3, f"causes share wording: {lines}"


@pytest.mark.parametrize("kind", ["no_network", "quota", "no_key"])
def test_state_returns_to_idle(monkeypatch, spoken, kind):
    """A turn that dies without transitioning leaves the listener stuck in
    SPEAKING, which then makes the wake word need barge-in loudness to fire."""
    monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
    trigger.handle_wake((np.ones(16000, dtype=np.int16) * 4000).tobytes())
    assert state_manager.current == AssistantState.IDLE
