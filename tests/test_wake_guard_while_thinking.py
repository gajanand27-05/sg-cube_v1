"""While a turn is THINKING, a wake needs barge-in loudness, as it already
did while SPEAKING.

2026-09-26: "onyx" decoded out of "good morning" 0.3s into a turn; that
capture ran on through the reply and Onyx's own sentence came back as the
user's words. Of that day's first 33 wakes, 9 fired while THINKING; transcribed,
8 of the 9 clips hold no "onyx" (204319 is ambiguous) — Vosk's two-word
grammar decodes room speech as the wake phrase.

The real-clip test reads the user's own wake clips from a local path and is
skipped when they (or the Vosk model) are missing; the clips hold the user's
voice and are never committed. The synthetic tests run everywhere.
"""
import json
import os
import wave
from pathlib import Path

import numpy as np
import pytest

from backend.core.state import AssistantState
from backend.daemon import wake_word as ww


@pytest.fixture
def listener(monkeypatch):
    monkeypatch.setattr(ww, "is_speaking", lambda: False)
    monkeypatch.setattr(ww.settings, "enable_barge_in", True)
    monkeypatch.setattr(ww.settings, "barge_in_rms_threshold", 800.0)
    obj = object.__new__(ww.WakeWordListener)
    obj.wake_phrase = "onyx"
    return obj


def _state(monkeypatch, s):
    monkeypatch.setattr(ww.state_manager, "_current_state", s, raising=False)


# ── synthetic (CI) ───────────────────────────────────────────────────────

@pytest.mark.parametrize("rms", [224, 322, 384, 388, 524, 578, 799])
def test_quiet_wake_is_ignored_while_thinking(listener, monkeypatch, rms):
    _state(monkeypatch, AssistantState.THINKING)
    assert listener._wake_trigger_allowed(rms) is False


@pytest.mark.parametrize("rms", [800, 1248, 3000])
def test_loud_wake_still_gets_through_while_thinking(listener, monkeypatch, rms):
    _state(monkeypatch, AssistantState.THINKING)
    assert listener._wake_trigger_allowed(rms) is True


@pytest.mark.parametrize("state", [AssistantState.IDLE, AssistantState.LISTENING])
def test_not_busy_is_unchanged(listener, monkeypatch, state):
    """A soft-spoken wake with no turn running is a real user."""
    _state(monkeypatch, state)
    assert listener._wake_trigger_allowed(54) is True


def test_barge_in_disabled_still_steps_aside(listener, monkeypatch):
    _state(monkeypatch, AssistantState.THINKING)
    monkeypatch.setattr(ww.settings, "enable_barge_in", False)
    assert listener._wake_trigger_allowed(54) is True


# ── the user's real wake clips (local only) ──────────────────────────────

CAPTURES = Path(os.environ.get(
    "SG_CUBE_CAPTURES", Path(__file__).resolve().parents[1] / "backend" / "database" / "captures"))
# Every wake of 2026-09-26 that fired while THINKING, and whether the rule
# blocks it. The last three show its limit: room speech is as loud as a wake.
THINKING_WAKES = {
    "203942-978": "blocked", "204319-584": "blocked", "204534-137": "blocked",
    "204559-019": "blocked", "204619-246": "blocked", "204627-711": "blocked",
    "203812-237": "allowed", "204648-754": "allowed", "204946-588": "allowed",
}
VOSK = ww.MODELS_DIR / ww.DEFAULT_MODEL
_present = VOSK.exists() and all(
    (CAPTURES / f"wake-20260926-{s}.wav").exists() for s in THINKING_WAKES)


@pytest.mark.skipif(not _present, reason="the user's local wake clips or the Vosk model are not present")
@pytest.mark.parametrize("stamp,expected", sorted(THINKING_WAKES.items()))
def test_real_thinking_wakes(listener, monkeypatch, stamp, expected):
    import vosk

    base = CAPTURES / f"wake-20260926-{stamp}"
    with wave.open(str(base.with_suffix(".wav"))) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    frames = [pcm[i:i + ww.WAKE_BLOCKSIZE] for i in range(0, len(pcm), ww.WAKE_BLOCKSIZE)]
    rms = lambda f: float(np.sqrt(np.mean(f.astype(np.float32) ** 2)))

    # The false wake reproduces offline: the listener's own grammar and gate.
    vosk.SetLogLevel(-1)
    rec = vosk.KaldiRecognizer(vosk.Model(str(VOSK)), 16000, json.dumps(["onyx", "[unk]"]))
    decoded = [ww.feed_wake_chunk(rec, f.tobytes()) for f in frames if rms(f) > ww._VAD_RMS_THRESHOLD]
    assert any(ww.wake_phrase_present(p, "onyx") for p in decoded)

    # The clip ends on the frame that fired; its loudness is the archived rms.
    trigger_rms = rms(frames[-1])
    assert round(trigger_rms) == json.loads(base.with_suffix(".json").read_text())["rms"]
    _state(monkeypatch, AssistantState.THINKING)
    assert listener._wake_trigger_allowed(trigger_rms) is (expected == "allowed")
