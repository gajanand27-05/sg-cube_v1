"""The selector is the revert switch. It must actually switch."""
import numpy as np
import pytest

from backend.ai_modules.speech import stt


def test_defaults_to_gemini(monkeypatch):
    monkeypatch.setattr(stt.settings, "stt_backend", "gemini")
    assert stt.active_backend() == "gemini"


def test_whisper_selectable(monkeypatch):
    monkeypatch.setattr(stt.settings, "stt_backend", "whisper")
    assert stt.active_backend() == "whisper"


def test_unknown_value_falls_back_to_the_primary_and_warns(monkeypatch, caplog):
    """A typo must land on the PRIMARY backend, which is groq since the move
    off Gemini — Gemini STT spends the planner's own 60/day budget, so
    defaulting a misconfiguration there quietly drains it."""
    monkeypatch.setattr(stt.settings, "stt_backend", "wisper")
    with caplog.at_level("WARNING"):
        assert stt.active_backend() == "groq"
    assert "wisper" in caplog.text


def test_groq_is_dispatched_to_when_selected(monkeypatch):
    calls = []
    monkeypatch.setattr(stt.settings, "stt_backend", "groq")
    monkeypatch.setattr(stt.stt_groq, "transcribe_array",
                        lambda a, sr=16000: calls.append("groq") or {"text": "g"})
    import numpy as np
    assert stt.transcribe_array(np.zeros(8, dtype=np.float32))["text"] == "g"
    assert calls == ["groq"]


def test_transcribe_array_dispatches_to_selected_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(stt.settings, "stt_backend", "whisper")
    monkeypatch.setattr(
        stt.stt_whisper, "transcribe_array",
        lambda a, sr=16000: calls.append("whisper") or {"text": "w"})
    monkeypatch.setattr(
        stt.stt_gemini, "transcribe_array",
        lambda a, sr=16000: calls.append("gemini") or {"text": "g"})

    out = stt.transcribe_array(np.zeros(16000, dtype=np.float32), 16000)
    assert calls == ["whisper"]
    assert out["text"] == "w"


def test_gemini_selected_dispatches_to_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(stt.settings, "stt_backend", "gemini")
    monkeypatch.setattr(
        stt.stt_whisper, "transcribe_array",
        lambda a, sr=16000: calls.append("whisper") or {"text": "w"})
    monkeypatch.setattr(
        stt.stt_gemini, "transcribe_array",
        lambda a, sr=16000: calls.append("gemini") or {"text": "g"})

    out = stt.transcribe_array(np.zeros(16000, dtype=np.float32), 16000)
    assert calls == ["gemini"]
    assert out["text"] == "g"
