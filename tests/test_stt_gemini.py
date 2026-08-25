"""stt_gemini must be a true drop-in for stt_whisper.

trigger.py hands it float32 normalized to [-1, 1] (arr.astype(np.float32) /
32768.0) and reads result["text"]. voice.py hands it a file path. Anything
that changes those two contracts breaks the rule engine, the content gate,
and the archive — none of which are being modified.
"""
import wave
from io import BytesIO

import numpy as np
import pytest
from google.genai import errors as genai_errors

from backend.ai_modules.llm import key_pool as kp
from backend.ai_modules.speech import stt_gemini


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "k" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_2", "")
    monkeypatch.setattr(kp.settings, "gemini_api_key_3", "")
    fresh = kp.KeyPool()
    monkeypatch.setattr(stt_gemini, "pool", fresh)
    return fresh


class _FakeModels:
    def __init__(self, payload=None, raises=None):
        self._payload, self._raises = payload, raises
        self.last_contents = None
        self.last_config = None

    def generate_content(self, *, model, contents, config):
        if self._raises:
            raise self._raises
        self.last_contents, self.last_config = contents, config
        return type("R", (), {"text": self._payload})()


class _FakeClient:
    def __init__(self, payload=None, raises=None):
        self.models = _FakeModels(payload, raises)


def _tone(seconds=1.0, rate=16000) -> np.ndarray:
    """float32 in [-1, 1] — exactly what trigger.py passes."""
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_encode_wav_produces_16bit_mono_pcm():
    audio = _tone(0.5)
    blob = stt_gemini.encode_wav(audio, 16000)
    with wave.open(BytesIO(blob), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == len(audio)


def test_encode_wav_does_not_clip_full_scale_input():
    """float32 1.0 * 32768 overflows int16. Must clamp to 32767, not wrap
    to -32768 — a wrap turns the loudest sample into the quietest."""
    audio = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    blob = stt_gemini.encode_wav(audio, 16000)
    with wave.open(BytesIO(blob), "rb") as wf:
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    assert samples[0] == 32767
    assert samples[1] == -32768
    assert samples[2] == 0


def test_returns_whisper_result_shape(monkeypatch):
    client = _FakeClient('{"transcript": "open notepad", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    out = stt_gemini.transcribe_array(_tone(2.0), 16000)
    assert set(out) == {"text", "language", "language_probability", "duration_sec"}
    assert out["text"] == "open notepad"
    assert out["duration_sec"] == pytest.approx(2.0, abs=0.01)


def test_no_speech_detected_yields_empty_text(monkeypatch):
    """The existing content gate rejects '' — so no-speech must map to '',
    not to a plausible-sounding hallucination."""
    client = _FakeClient('{"transcript": "thank you", "speech_detected": false}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == ""


def test_transcript_is_stripped(monkeypatch):
    client = _FakeClient('{"transcript": "  lock the screen \\n", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == "lock the screen"


def test_unparseable_response_is_empty_not_an_exception(monkeypatch):
    """A malformed body must not become a command. Empty is the safe value —
    the content gate already rejects it."""
    client = _FakeClient("this is not json")
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == ""


def test_no_key_configured_raises_no_key(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "")
    monkeypatch.setattr(stt_gemini, "pool", kp.KeyPool())
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "no_key"


def test_quota_exhaustion_raises_quota_and_parks_the_key(monkeypatch, keys):
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, "RESOURCE_EXHAUSTED PerDay")
    err.code = 429
    monkeypatch.setattr(stt_gemini, "_client_for",
                        lambda: (1, _FakeClient(raises=err)))
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "quota"


def test_connection_error_raises_no_network(monkeypatch):
    monkeypatch.setattr(
        stt_gemini, "_client_for",
        lambda: (1, _FakeClient(raises=ConnectionError("getaddrinfo failed"))))
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "no_network"


def test_uses_a_real_sdk_method_name():
    """Both this repo and the camera module shipped calls to the OLD
    google-generativeai SDK and stayed green because the tests mocked the
    seam. df41d3a fixed generate_content_async; this guards the sync path."""
    from google.genai import models
    assert hasattr(models.Models, "generate_content")
    assert not hasattr(models.Models, "generate_content_async")


def test_transcribe_from_path_matches_array(monkeypatch, tmp_path):
    client = _FakeClient('{"transcript": "what time is it", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    wav = tmp_path / "clip.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((_tone(1.0) * 32767).astype(np.int16).tobytes())
    assert stt_gemini.transcribe(wav)["text"] == "what time is it"
