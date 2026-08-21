"""Onyx must not wake itself on its own voice, or turn noise into turns.

From a live session, repeated dozens of times:

    [wake] heard wake: 'onyx' (rms=54)
    [TTS] Speech interrupted
    [command] ''
    [trigger] dropping non-command transcript ''
    [wake] empty capture (1/2); still listening

Two separate holes produced that loop.

1. The WAKE path had no state check. Barge-in is guarded — it only fires
   during SPEAKING, needs rms >= barge_in_rms_threshold (800) and a debounce.
   The bare `wake_phrase in partial` test next to it had none of that, so TTS
   bleeding back into the mic decoded as "onyx" and started a turn at rms=54,
   interrupting the sentence Onyx was still speaking. Every barge-in
   protection was bypassed by sitting in the other branch.

2. The FOLLOW-UP path fires on token growth alone, with no loudness floor at
   all. That is deliberate — near-silence must not qualify — but it means
   room noise decoding to "[unk]" starts a full turn. Observed firing at
   rms=64, 106, 178, 197, 203, each producing an empty capture.

Both gates are loudness floors on the TRIGGER, not on what reaches the
recognizer. Raising the recognizer's own feed threshold was tried and
reverted: it starves Vosk of the quiet frames between words and it starts
hallucinating the wake phrase out of ordinary speech (see the measurement in
_VAD_RMS_THRESHOLD's comment).
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.state import AssistantState
from backend.daemon import wake_word as ww


@pytest.fixture
def listener():
    obj = object.__new__(ww.WakeWordListener)
    obj.wake_phrase = "onyx"
    return obj


# ── wake while Onyx is speaking ──────────────────────────────────────────

@pytest.mark.parametrize("rms", [54, 66, 96, 133, 256, 553, 799])
def test_quiet_wake_is_ignored_while_speaking(listener, monkeypatch, rms):
    """Every one of these fired a real turn in the live log, mid-sentence."""
    monkeypatch.setattr(ww.state_manager, "_current_state",
                        AssistantState.SPEAKING, raising=False)
    assert listener._wake_trigger_allowed(rms) is False


@pytest.mark.parametrize("rms", [800, 1732, 4063])
def test_a_genuinely_loud_wake_still_interrupts(listener, monkeypatch, rms):
    """Saying "onyx" over the top of a reply must still work — that is the
    whole point of being interruptible."""
    monkeypatch.setattr(ww.state_manager, "_current_state",
                        AssistantState.SPEAKING, raising=False)
    assert listener._wake_trigger_allowed(rms) is True


@pytest.mark.parametrize("rms", [54, 96, 800, 4063])
def test_any_wake_is_allowed_when_not_speaking(listener, monkeypatch, rms):
    """Idle is the normal case and must not get stricter — a soft-spoken wake
    at rms=54 with nothing playing is a real user."""
    monkeypatch.setattr(ww.state_manager, "_current_state",
                        AssistantState.IDLE, raising=False)
    assert listener._wake_trigger_allowed(rms) is True


def test_the_guard_defers_to_barge_in_being_enabled(listener, monkeypatch):
    """With barge-in off there is no other way to interrupt, so suppressing
    the wake would make Onyx uninterruptible for the length of a reply."""
    monkeypatch.setattr(ww.state_manager, "_current_state",
                        AssistantState.SPEAKING, raising=False)
    monkeypatch.setattr(ww.settings, "enable_barge_in", False)
    assert listener._wake_trigger_allowed(54) is True


# ── follow-up on room noise ──────────────────────────────────────────────

@pytest.mark.parametrize("rms", [64, 106, 178, 197, 203])
def test_quiet_noise_does_not_open_a_followup_turn(listener, rms):
    """Each of these started a turn that captured nothing."""
    assert listener._followup_trigger_allowed(rms) is False


@pytest.mark.parametrize("rms", [975, 1288, 1769, 2908])
def test_real_follow_up_speech_still_triggers(listener, rms):
    """The continuous-conversation feature has to keep working; these are the
    follow-ups from the same log that carried actual commands."""
    assert listener._followup_trigger_allowed(rms) is True


def test_the_followup_floor_sits_below_the_barge_in_floor(listener):
    """A follow-up is a user talking to a SILENT assistant, so it must not
    need to be as loud as talking over one. If these ever invert, follow-up
    becomes the harder of the two and continuous conversation dies."""
    from backend.server.config import settings
    assert ww._FOLLOWUP_MIN_RMS < settings.barge_in_rms_threshold
