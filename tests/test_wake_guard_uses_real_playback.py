"""T-quiet-wake-cuts-speech.

`_wake_trigger_allowed` asks the STATE MACHINE whether we are speaking, and
requires barge-in loudness only then. That guard exists precisely so our own
TTS bleeding back into the mic cannot decode as "onyx" and cut the sentence
being spoken.

But the state machine can say IDLE while audio is still coming out of the
speaker. Overlapping turns are the ordinary way: turn A is mid-reply when
turn B finishes and runs its own `transition_to(IDLE)`. From then on A's
playback is unguarded, and the log is full of what that looks like —

    [wake] heard wake: 'onyx' (rms=88)
    [TTS] Speech interrupted
    [wake] heard wake: 'onyx' (rms=73)
    [TTS] Speech interrupted
    [wake] heard wake: '[unk] onyx' (rms=59)
    [TTS] Speech interrupted

— wakes far below any plausible speech level, each one cutting a sentence.
Note the guard cannot be fixed by raising an RMS floor: while nothing is
playing, a genuinely quiet "onyx" is a wake we want, and _VAD_RMS_THRESHOLD
is load-bearing at 50 and must not move. The defect is the question, not the
threshold. tts_piper.is_speaking() knows the answer exactly.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.state import AssistantState, manager as state_manager
from backend.daemon.wake_word import WakeWordListener
from backend.server.config import settings


def _listener() -> WakeWordListener:
    """A listener without a Vosk model — we only exercise the guard."""
    return object.__new__(WakeWordListener)


def test_quiet_wake_is_refused_while_audio_is_actually_playing():
    """The reported case: playback live, state machine already back to IDLE."""
    lis = _listener()
    state_manager.transition_to(AssistantState.IDLE)

    with patch("backend.daemon.wake_word.is_speaking", return_value=True):
        assert lis._wake_trigger_allowed(59) is False
        assert lis._wake_trigger_allowed(88) is False
        assert lis._wake_trigger_allowed(342) is False


def test_loud_wake_still_interrupts_playback():
    """Talking over the assistant must keep working — that is barge-in."""
    lis = _listener()
    state_manager.transition_to(AssistantState.IDLE)

    with patch("backend.daemon.wake_word.is_speaking", return_value=True):
        assert lis._wake_trigger_allowed(settings.barge_in_rms_threshold) is True
        assert lis._wake_trigger_allowed(2500) is True


def test_quiet_wake_is_allowed_when_nothing_is_playing():
    """Silence is where a soft 'onyx' has to work. No floor here."""
    lis = _listener()
    state_manager.transition_to(AssistantState.IDLE)

    with patch("backend.daemon.wake_word.is_speaking", return_value=False):
        assert lis._wake_trigger_allowed(59) is True
        assert lis._wake_trigger_allowed(342) is True


def test_state_machine_speaking_still_guards_on_its_own():
    """Belt and braces: either signal saying 'speaking' is enough."""
    lis = _listener()
    state_manager.transition_to(AssistantState.SPEAKING)
    try:
        with patch("backend.daemon.wake_word.is_speaking", return_value=False):
            assert lis._wake_trigger_allowed(59) is False
            assert lis._wake_trigger_allowed(2500) is True
    finally:
        state_manager.transition_to(AssistantState.IDLE)


def test_guard_steps_aside_when_barge_in_is_disabled():
    """With barge-in off there is no other way to interrupt — unchanged."""
    lis = _listener()
    state_manager.transition_to(AssistantState.SPEAKING)
    try:
        with patch.object(settings, "enable_barge_in", False), \
             patch("backend.daemon.wake_word.is_speaking", return_value=True):
            assert lis._wake_trigger_allowed(59) is True
    finally:
        state_manager.transition_to(AssistantState.IDLE)


def teardown_function(_fn):
    state_manager.transition_to(AssistantState.IDLE)
