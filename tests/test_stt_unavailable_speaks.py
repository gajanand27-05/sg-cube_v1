"""When STT cannot run, say so — differently per cause — and reach IDLE.

Silence is not acceptable and neither is one generic line. 59eb62f fixed
exactly this shape of bug: being interrupted and being misheard produced the
same sentence, so the user was told they had been misheard when they had not.
Piper is local and still works in every case here.

The `spoken` fixture patches `trigger.speak_stream`, NOT `trigger.speak`.
That is deliberate and load-bearing. The first cut of this feature called
`speak(line)`, which is fire-and-forget under a running loop, and `handle_wake`
tears the loop down one line later — production heard nothing. A fixture on
`trigger.speak` recorded the call anyway and stayed green through it. The
seam has to be the one production actually drives to the speaker.
"""
import numpy as np
import pytest

from backend.ai_modules.speech.stt_gemini import SttUnavailable
from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import trigger


@pytest.fixture(autouse=True)
def _no_speech_gate(monkeypatch):
    """These tests are about what Onyx SAYS when STT cannot run, so the audio
    has to reach STT.

    `_audio()` below is a DC constant, not speech — silero scores it at zero
    seconds and the post-wake speech gate drops it before STT is ever called,
    which is the gate behaving correctly. Turning the gate off here keeps each
    test pointed at its own subject instead of silently re-testing the gate.
    """
    from backend.server.config import settings

    monkeypatch.setattr(settings, "enable_speech_gate", False)


def _audio():
    return (np.ones(16000, dtype=np.int16) * 4000).tobytes()


def _patch_speech(monkeypatch):
    """Record every sentence that reaches the local playback stream."""
    said: list[str] = []

    async def _fake_stream(text, *a, **k):
        said.append(text)
        if False:  # pragma: no cover - keeps this an async generator
            yield b""

    monkeypatch.setattr(trigger, "speak_stream", _fake_stream)
    monkeypatch.setattr(trigger, "_play_chime", lambda: None)
    return said


@pytest.fixture
def spoken(monkeypatch):
    return _patch_speech(monkeypatch)


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

    assert trigger.handle_wake(_audio()) is False

    assert len(spoken) == 1, f"{kind} spoke {spoken!r}, expected one sentence"
    assert needle in spoken[0].lower(), f"{kind} said {spoken[0]!r}"


def test_the_three_lines_are_distinct(monkeypatch):
    """If two causes share a sentence, the user cannot tell them apart —
    which is the bug 59eb62f fixed, reintroduced."""
    lines = set()
    for kind in ("no_network", "quota", "no_key"):
        said = _patch_speech(monkeypatch)
        monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
        assert trigger.handle_wake(_audio()) is False
        assert len(said) == 1, f"{kind} spoke {said!r}, expected one sentence"
        lines.add(said[0])
    assert len(lines) == 3, f"causes share wording: {lines}"


@pytest.mark.parametrize("kind", ["no_network", "quota", "no_key"])
def test_state_returns_to_idle(monkeypatch, spoken, kind):
    """A turn that dies without transitioning leaves the listener stuck in
    SPEAKING, which then makes the wake word need barge-in loudness to fire.

    The `crashes` assertion is what makes this test discriminating. Reaching
    IDLE on its own proves nothing: SttUnavailable subclasses RuntimeError, so
    the pre-existing generic `except Exception` handler already transitioned to
    IDLE before this feature existed. What that handler ALSO does — and the
    STT-unavailable branch deliberately does not — is go through ERROR and
    record a crash. Delete the branch and this test goes red on `crashes`.
    """
    crashes = []
    monkeypatch.setattr(
        trigger.dogfooding_ledger, "record_crash", lambda *a, **k: crashes.append(1))
    monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))

    assert trigger.handle_wake(_audio()) is False

    assert state_manager.current == AssistantState.IDLE
    assert not crashes, "took the generic crash path, not the STT-unavailable branch"


def test_the_notice_goes_to_the_device_that_asked(monkeypatch, spoken):
    """A turn driven from a remote device must not answer on the desktop
    speaker the user is not standing next to. The failure branch carries the
    same device_id the successful path routes on."""
    routed = []

    async def _fake_selective(text, device_id=None):
        routed.append((text, device_id))

    monkeypatch.setattr(trigger, "_speak_selective", _fake_selective)
    monkeypatch.setattr(trigger, "transcribe_array", _raise("no_network"))

    assert trigger.handle_wake(_audio(), None, "phone-42") is False

    assert routed == [(trigger._STT_UNAVAILABLE_SPEECH["no_network"], "phone-42")]


def test_the_hud_is_told_what_was_said(monkeypatch, spoken):
    """Without a SpokenResponse the HUD keeps rendering the PREVIOUS turn's
    answer while Onyx says it cannot reach the network — a successful answer
    displayed next to a failed turn."""
    from backend.daemon.ui_events import SpokenResponse

    published = []
    emitted = []

    class _FakeBus:
        def publish(self, event, priority=None):
            published.append(event)

    monkeypatch.setattr(trigger, "get_bus", lambda: _FakeBus())
    monkeypatch.setattr(trigger, "transcribe_array", _raise("quota"))

    assert trigger.handle_wake(_audio(), emitted.append) is False

    texts = [e.text for e in published if isinstance(e, SpokenResponse)]
    assert texts == [trigger._STT_UNAVAILABLE_SPEECH["quota"]], published
    assert [e.text for e in emitted if isinstance(e, SpokenResponse)] == texts


def test_the_notice_is_spoken_in_the_speaking_state(monkeypatch, spoken):
    """Onyx must be in SPEAKING while the notice plays, not THINKING.

    wake_word._followup_trigger_allowed early-returns unless the state is
    SPEAKING, so a notice delivered from THINKING is one the user cannot
    interrupt — the Vosk-token barge-in path is inert for its whole duration
    while Onyx is audibly talking. The HUD also reads "thinking" over speech,
    which is the stale-pairing that makes dogfooding logs misleading.
    """
    seen: list[AssistantState] = []

    async def _fake_stream(text, *a, **k):
        seen.append(state_manager.current)
        if False:  # pragma: no cover - keeps this an async generator
            yield b""

    monkeypatch.setattr(trigger, "speak_stream", _fake_stream)
    monkeypatch.setattr(trigger, "transcribe_array", _raise("no_network"))

    trigger.handle_wake(_audio())

    assert seen == [AssistantState.SPEAKING], (
        f"notice was spoken from {seen!r}, not SPEAKING"
    )
    assert state_manager.current == AssistantState.IDLE


def test_the_failed_turn_records_a_first_audio_mark(monkeypatch, spoken):
    """Without it the turn carries only `wake` and /diagnostics/latency
    cannot compare a failed turn against a good one."""
    recorded: list = []
    monkeypatch.setattr(trigger, "transcribe_array", _raise("quota"))
    monkeypatch.setattr(
        trigger.latency_ledger(), "record", lambda t: recorded.append(t)
    )

    trigger.handle_wake(_audio())

    assert recorded, "the failed turn was never recorded"
    assert "first_audio_out" in recorded[0].stages, (
        f"stages were {list(recorded[0].stages)}"
    )
