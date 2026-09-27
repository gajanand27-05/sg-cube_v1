"""The turn log records when Onyx's first audio actually PLAYED
("first_sound"), and the HUD gets it as its headline (reply_latency).

first_audio_out only marks the first sentence being ready; Piper still has to
synthesize it (0.14-0.78s measured), so it understated the wait. The TTS
history and the event bus are faked; nothing is played.
"""
import time
from collections import deque

from backend.ai_modules.speech import tts_piper
from backend.core import latency
from backend.daemon.ui_events import ReplyLatencyEvent


def test_first_sound_is_marked_and_published(monkeypatch):
    monkeypatch.setattr(tts_piper, "_recent_spoken", deque(maxlen=8))
    published = []
    import backend.core.events as events
    monkeypatch.setattr(events, "get_bus", lambda: type("B", (), {"publish": lambda self, e, **k: published.append(e)})())

    turn = latency.TurnLatency(request_id="r1")
    old = tts_piper._Utterance("earlier", ("earlier",), started_at=0.0, played_at=turn._start_perf - 5)
    now = tts_piper._Utterance("hi", ("hi",), started_at=0.0, played_at=turn._start_perf + 1.25)
    tts_piper._recent_spoken.extend([old, now])

    ledger = latency.LatencyLedger()
    ledger.record(turn)

    assert ledger.recent(1)[0]["stages_ms"]["first_sound"] == 1250
    assert [e for e in published if isinstance(e, ReplyLatencyEvent)] == [
        ReplyLatencyEvent(first_word_ms=1250, request_id="r1")]


def test_a_turn_with_no_speech_has_no_first_sound(monkeypatch):
    monkeypatch.setattr(tts_piper, "_recent_spoken", deque(maxlen=8))
    ledger = latency.LatencyLedger()
    ledger.record(latency.TurnLatency(request_id="r2"))
    assert "first_sound" not in ledger.recent(1)[0]["stages_ms"]
