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
# Read from tools/_wake/keep/ (tools/keep_captures.py), where recordings are
# never pruned; the manifest records what Onyx was doing when each wake fired.
# Skipped when the folder is missing (CI, another machine): the clips are the
# user's voice and never committed. The 2026-09-26 clips this used to name
# were pruned by the capture archive, which is why the keep folder exists.

KEEP = Path(os.environ.get("SG_CUBE_KEEP", Path(__file__).resolve().parents[1] / "tools" / "_wake" / "keep"))


def _thinking_wakes(limit: int = 9) -> list[dict]:
    try:
        manifest = json.loads((KEEP / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in manifest if m["category"] == "wake_trigger"
            and m.get("assistant_state") == "THINKING" and (KEEP / m["file"]).exists()][:limit]


_CLIPS = _thinking_wakes()


@pytest.mark.skipif(not _CLIPS, reason="no kept wake clips (tools/_wake/keep) on this machine")
@pytest.mark.parametrize("clip", _CLIPS or [None], ids=lambda c: c["file"] if c else "none")
def test_real_thinking_wakes(listener, monkeypatch, clip):
    with wave.open(str(KEEP / clip["file"])) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    # The clip ends on the frame that fired; its loudness is the archived rms.
    last = pcm[-ww.WAKE_BLOCKSIZE:]
    trigger_rms = float(np.sqrt(np.mean(last.astype(np.float32) ** 2)))
    assert round(trigger_rms) == clip["trigger_rms"]
    _state(monkeypatch, AssistantState.THINKING)
    assert listener._wake_trigger_allowed(trigger_rms) is (trigger_rms >= 800)
