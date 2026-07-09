"""Phase 4A — barge-in.

Two axes:
  * The pure debounce/threshold logic on WakeWordListener (no Vosk, no mic).
  * The trigger.on_barge_in() callback: stop_speech + state transition +
    SpeechInterruptedEvent published.

WakeWordListener __init__ loads a Vosk model, so we bypass it with
object.__new__ and only set the state the method under test needs.
"""
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event, priority=None):
        self.published.append(event)


def _make_listener():
    from backend.daemon.wake_word import WakeWordListener
    listener = object.__new__(WakeWordListener)
    listener._barge_in_frames = 0
    return listener


def _set_state(state):
    from backend.core.state import manager
    manager._current_state = state


# ── _check_barge_in unit tests (no Vosk, no mic) ────────────────────────

def test_barge_in_fires_after_debounce_only():
    from backend.core.state import AssistantState
    from backend.server.config import settings
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    orig_t, orig_d, orig_e = (
        settings.barge_in_rms_threshold,
        settings.barge_in_debounce_frames,
        settings.enable_barge_in,
    )
    try:
        settings.enable_barge_in = True
        settings.barge_in_rms_threshold = 500
        settings.barge_in_debounce_frames = 3
        # Two frames above threshold — no fire yet
        assert listener._check_barge_in(1000) is False
        assert listener._check_barge_in(1200) is False
        # Third frame → fire, counter resets
        assert listener._check_barge_in(1500) is True
        assert listener._barge_in_frames == 0
        # Right after firing, need to re-accumulate
        assert listener._check_barge_in(1500) is False
    finally:
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        settings.enable_barge_in = orig_e
        _set_state(AssistantState.IDLE)
    print("  [PASS] fires only after N consecutive high-RMS frames")


def test_barge_in_debounce_resets_on_low_rms():
    from backend.core.state import AssistantState
    from backend.server.config import settings
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    orig_t, orig_d, orig_e = (
        settings.barge_in_rms_threshold,
        settings.barge_in_debounce_frames,
        settings.enable_barge_in,
    )
    try:
        settings.enable_barge_in = True
        settings.barge_in_rms_threshold = 500
        settings.barge_in_debounce_frames = 3
        assert listener._check_barge_in(1000) is False
        assert listener._check_barge_in(1000) is False
        # One quiet frame → counter resets
        assert listener._check_barge_in(100) is False
        assert listener._barge_in_frames == 0
        # Have to re-accumulate the full N
        assert listener._check_barge_in(1000) is False
        assert listener._check_barge_in(1000) is False
        assert listener._check_barge_in(1000) is True
    finally:
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        settings.enable_barge_in = orig_e
        _set_state(AssistantState.IDLE)
    print("  [PASS] counter resets on any sub-threshold frame")


def test_barge_in_ignored_when_not_speaking():
    from backend.core.state import AssistantState
    from backend.server.config import settings
    listener = _make_listener()
    _set_state(AssistantState.IDLE)  # NOT speaking
    orig_t, orig_d, orig_e = (
        settings.barge_in_rms_threshold,
        settings.barge_in_debounce_frames,
        settings.enable_barge_in,
    )
    try:
        settings.enable_barge_in = True
        settings.barge_in_rms_threshold = 500
        settings.barge_in_debounce_frames = 1  # would fire immediately if we let it
        assert listener._check_barge_in(9999) is False
        assert listener._check_barge_in(9999) is False
        assert listener._barge_in_frames == 0
    finally:
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        settings.enable_barge_in = orig_e
    print("  [PASS] never fires outside SPEAKING state")


def test_barge_in_disabled_by_config():
    from backend.core.state import AssistantState
    from backend.server.config import settings
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    orig_t, orig_d, orig_e = (
        settings.barge_in_rms_threshold,
        settings.barge_in_debounce_frames,
        settings.enable_barge_in,
    )
    try:
        settings.enable_barge_in = False  # kill switch
        settings.barge_in_rms_threshold = 500
        settings.barge_in_debounce_frames = 1
        assert listener._check_barge_in(9999) is False
        assert listener._check_barge_in(9999) is False
    finally:
        settings.enable_barge_in = orig_e
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        _set_state(AssistantState.IDLE)
    print("  [PASS] enable_barge_in=False fully disables the check")


def test_barge_in_state_change_mid_debounce_resets():
    from backend.core.state import AssistantState
    from backend.server.config import settings
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    orig_t, orig_d, orig_e = (
        settings.barge_in_rms_threshold,
        settings.barge_in_debounce_frames,
        settings.enable_barge_in,
    )
    try:
        settings.enable_barge_in = True
        settings.barge_in_rms_threshold = 500
        settings.barge_in_debounce_frames = 3
        assert listener._check_barge_in(1000) is False  # count=1
        assert listener._check_barge_in(1000) is False  # count=2
        # State transitions out mid-debounce
        _set_state(AssistantState.IDLE)
        assert listener._check_barge_in(1000) is False
        assert listener._barge_in_frames == 0
    finally:
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        settings.enable_barge_in = orig_e
        _set_state(AssistantState.IDLE)
    print("  [PASS] partial debounce doesn't leak across state transition")


# ── on_barge_in trigger callback tests ─────────────────────────────────

def test_on_barge_in_calls_stop_speech_and_publishes_interrupt():
    from backend.daemon.trigger import on_barge_in
    from backend.daemon.ui_events import SpeechInterruptedEvent, WakeHeard
    bus = _FakeBus()
    with patch("backend.daemon.trigger.stop_speech") as m_stop, \
         patch("backend.daemon.trigger.commander") as m_cmdr, \
         patch("backend.daemon.trigger.get_bus", return_value=bus), \
         patch("backend.daemon.trigger.threading.Thread"), \
         patch("backend.daemon.trigger.state_manager") as m_state:
        on_barge_in(rms=1234.5, emit=None)
    m_stop.assert_called_once()
    m_cmdr.interrupt.assert_called_once()
    m_state.transition_to.assert_called_once()
    types = [type(e).__name__ for e in bus.published]
    assert "SpeechInterruptedEvent" in types, f"expected SpeechInterruptedEvent, got {types}"
    assert "WakeHeard" in types, f"expected WakeHeard also (barge-in IS a wake), got {types}"
    si = next(e for e in bus.published if isinstance(e, SpeechInterruptedEvent))
    assert si.rms == 1234.5
    print("  [PASS] on_barge_in: stops TTS, transitions state, publishes SpeechInterrupted+WakeHeard")


def test_on_wake_detected_does_not_publish_speech_interrupted():
    """Regression: normal wake path must NOT publish SpeechInterruptedEvent."""
    from backend.daemon.trigger import on_wake_detected
    from backend.daemon.ui_events import SpeechInterruptedEvent
    bus = _FakeBus()
    with patch("backend.daemon.trigger.stop_speech"), \
         patch("backend.daemon.trigger.commander"), \
         patch("backend.daemon.trigger.get_bus", return_value=bus), \
         patch("backend.daemon.trigger.threading.Thread"), \
         patch("backend.daemon.trigger.state_manager"):
        on_wake_detected(emit=None)
    for e in bus.published:
        assert not isinstance(e, SpeechInterruptedEvent), (
            "wake path emitting SpeechInterruptedEvent would confuse the "
            "frontend transition (Speaking→Listening vs Idle→Listening)"
        )
    print("  [PASS] wake path does NOT emit SpeechInterruptedEvent (regression guard)")


if __name__ == "__main__":
    test_barge_in_fires_after_debounce_only()
    test_barge_in_debounce_resets_on_low_rms()
    test_barge_in_ignored_when_not_speaking()
    test_barge_in_disabled_by_config()
    test_barge_in_state_change_mid_debounce_resets()
    test_on_barge_in_calls_stop_speech_and_publishes_interrupt()
    test_on_wake_detected_does_not_publish_speech_interrupted()
    print("All Phase 4A barge-in tests passed.")
