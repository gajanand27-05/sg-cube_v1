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
    listener._partial_tokens = 0
    listener._barge_in_saw_speech = False
    return listener


class _Speech:
    """Cumulative Vosk partials, as the real recognizer produces them.

    Measured against the live model: with the restricted grammar the user's
    words come back as "[unk]" tokens, the string only ever grows within an
    utterance, and it keeps being returned unchanged on silent frames. Call
    `.grow()` for a frame where Vosk decoded something new, `.same()` for a
    frame where it did not.
    """

    def __init__(self):
        self.tokens = []

    def grow(self) -> str:
        self.tokens.append("[unk]")
        return " ".join(self.tokens)

    def same(self) -> str:
        return " ".join(self.tokens)


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
        speech = _Speech()
        # Two frames above threshold — no fire yet
        assert listener._check_barge_in(1000, speech.grow()) is False
        assert listener._check_barge_in(1200, speech.same()) is False
        # Third frame → fire, counter resets
        assert listener._check_barge_in(1500, speech.grow()) is True
        assert listener._barge_in_frames == 0
        # Right after firing, need to re-accumulate
        assert listener._check_barge_in(1500, speech.grow()) is False
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
        speech = _Speech()
        assert listener._check_barge_in(1000, speech.grow()) is False
        assert listener._check_barge_in(1000, speech.same()) is False
        # One quiet frame → counter resets
        assert listener._check_barge_in(100, speech.same()) is False
        assert listener._barge_in_frames == 0
        # Have to re-accumulate the full N
        assert listener._check_barge_in(1000, speech.grow()) is False
        assert listener._check_barge_in(1000, speech.same()) is False
        assert listener._check_barge_in(1000, speech.grow()) is True
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
        speech = _Speech()
        assert listener._check_barge_in(9999, speech.grow()) is False
        assert listener._check_barge_in(9999, speech.grow()) is False
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
        speech = _Speech()
        assert listener._check_barge_in(9999, speech.grow()) is False
        assert listener._check_barge_in(9999, speech.grow()) is False
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
        speech = _Speech()
        assert listener._check_barge_in(1000, speech.grow()) is False  # count=1
        assert listener._check_barge_in(1000, speech.same()) is False  # count=2
        # State transitions out mid-debounce
        _set_state(AssistantState.IDLE)
        assert listener._check_barge_in(1000, speech.grow()) is False
        assert listener._barge_in_frames == 0
    finally:
        settings.barge_in_rms_threshold = orig_t
        settings.barge_in_debounce_frames = orig_d
        settings.enable_barge_in = orig_e
        _set_state(AssistantState.IDLE)
    print("  [PASS] partial debounce doesn't leak across state transition")


# ── speech gate: loudness alone must not interrupt ─────────────────────

def _speech_settings(**over):
    """Context-free helper: set barge-in settings, return restore thunk."""
    from backend.server.config import settings
    keys = (
        "enable_barge_in",
        "barge_in_rms_threshold",
        "barge_in_debounce_frames",
        "barge_in_require_speech",
    )
    saved = {k: getattr(settings, k) for k in keys}
    settings.enable_barge_in = True
    settings.barge_in_rms_threshold = 500
    settings.barge_in_debounce_frames = 2
    settings.barge_in_require_speech = True
    for k, v in over.items():
        setattr(settings, k, v)
    return lambda: [setattr(settings, k, v) for k, v in saved.items()]


def test_loud_non_speech_never_fires():
    """The reported bug: room transients at ~2854 RMS against an 800
    threshold self-interrupted playback. Vosk decodes nothing from
    non-speech — a click train at 3085 RMS and a 220Hz tone at 5656 RMS
    both produce an empty partial — so the token count never moves."""
    from backend.core.state import AssistantState
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    restore = _speech_settings()
    try:
        for _ in range(20):
            assert listener._check_barge_in(2854, "") is False
        # Sustained and much louder still decodes to nothing.
        for _ in range(20):
            assert listener._check_barge_in(9999, "") is False
    finally:
        restore()
        _set_state(AssistantState.IDLE)
    print("  [PASS] loud non-speech never interrupts playback")


def test_speech_still_fires():
    """The gate must not cost us barge-in itself."""
    from backend.core.state import AssistantState
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    restore = _speech_settings()
    speech = _Speech()
    try:
        assert listener._check_barge_in(1500, speech.grow()) is False
        assert listener._check_barge_in(1500, speech.grow()) is True
    finally:
        restore()
        _set_state(AssistantState.IDLE)
    print("  [PASS] real speech still interrupts playback")


def test_cumulative_partial_does_not_latch_the_gate():
    """PartialResult keeps returning the whole accumulated string on silent
    frames. A non-emptiness check would therefore stay True for the rest of
    the utterance and every later noise burst would ride in on it."""
    from backend.core.state import AssistantState
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    restore = _speech_settings()
    speech = _Speech()
    try:
        # One real utterance fires.
        assert listener._check_barge_in(1500, speech.grow()) is False
        assert listener._check_barge_in(1500, speech.grow()) is True
        # Now noise, while the partial still reads '[unk] [unk]' — non-empty
        # but not growing. Must not fire again.
        for _ in range(10):
            assert listener._check_barge_in(3000, speech.same()) is False
    finally:
        restore()
        _set_state(AssistantState.IDLE)
    print("  [PASS] stale non-empty partial does not re-arm the gate")


def test_debounce_satisfied_early_fires_when_speech_arrives_later():
    """Loud frames may precede the first decoded token by a frame or two.
    Once the debounce count is met, the first growth frame should fire
    rather than restarting the whole count."""
    from backend.core.state import AssistantState
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    restore = _speech_settings(barge_in_debounce_frames=2)
    speech = _Speech()
    try:
        assert listener._check_barge_in(1500, "") is False  # loud, undecoded
        assert listener._check_barge_in(1500, "") is False  # count met, no speech
        assert listener._check_barge_in(1500, "") is False  # still nothing
        assert listener._check_barge_in(1500, speech.grow()) is True
    finally:
        restore()
        _set_state(AssistantState.IDLE)
    print("  [PASS] fires on the first decoded token once debounce is met")


def test_require_speech_false_restores_loudness_only():
    """Escape hatch for a mic too quiet for Vosk to decode at all."""
    from backend.core.state import AssistantState
    listener = _make_listener()
    _set_state(AssistantState.SPEAKING)
    restore = _speech_settings(barge_in_require_speech=False)
    try:
        assert listener._check_barge_in(1500, "") is False
        assert listener._check_barge_in(1500, "") is True
    finally:
        restore()
        _set_state(AssistantState.IDLE)
    print("  [PASS] barge_in_require_speech=False is loudness-only again")


def test_legacy_word_gate_rejects_real_partials():
    """Guard on the reason this fix exists: `_has_followup_content` asks for
    alphabetic words, and under our restricted grammar real speech arrives
    as '[unk]'. Anything gated on it is gated on saying the wake word again.
    Measured against the live model on two recorded clips."""
    from backend.daemon.wake_word import _has_followup_content, _partial_grew
    for partial in ["[unk]", "[unk] [unk]", "[unk] [unk] [unk]"]:
        assert not _has_followup_content(partial), repr(partial)
    # The replacement sees them for what they are: decoded speech.
    assert _partial_grew("[unk]", 0)
    assert _partial_grew("[unk] [unk]", 1)
    assert not _partial_grew("[unk] [unk]", 2)
    assert not _partial_grew("", 0)
    print("  [PASS] legacy word gate is blind to real partials; growth gate is not")


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
    # isinstance against the IMPORTED classes, not type(e).__name__.
    # A name check passes for a look-alike class defined somewhere else, and
    # that is not hypothetical here: agents/base.py shadowed
    # InternalAgentEvent for months, so every _emit() published a class the bus
    # had no subscriber for and ws_ui had never heard of. The bus dispatches on
    # identity, so the test has to as well.
    types = [type(e).__name__ for e in bus.published]
    assert any(isinstance(e, SpeechInterruptedEvent) for e in bus.published), (
        f"expected SpeechInterruptedEvent, got {types}")
    assert any(isinstance(e, WakeHeard) for e in bus.published), (
        f"expected WakeHeard also (barge-in IS a wake), got {types}")
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
    test_loud_non_speech_never_fires()
    test_speech_still_fires()
    test_cumulative_partial_does_not_latch_the_gate()
    test_debounce_satisfied_early_fires_when_speech_arrives_later()
    test_require_speech_false_restores_loudness_only()
    test_legacy_word_gate_rejects_real_partials()
    test_on_barge_in_calls_stop_speech_and_publishes_interrupt()
    test_on_wake_detected_does_not_publish_speech_interrupted()
    print("All Phase 4A barge-in tests passed.")
