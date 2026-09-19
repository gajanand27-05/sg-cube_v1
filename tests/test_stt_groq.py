"""Groq is the primary STT; Gemini is the safety net under it.

The property that matters is that a Groq failure NEVER ends the turn — it
demotes to Gemini. Getting that wrong trades a quota problem for a silence
problem, which is strictly worse.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import stt_groq
from backend.ai_modules.speech.stt_gemini import SttUnavailable


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {"text": "open notepad"}
        self.text = text

    def json(self):
        return self._payload


def _client(resp):
    class _C:
        def __init__(self_inner, *a, **kw):
            pass

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def post(self_inner, *a, **kw):
            _C.sent = kw
            if isinstance(resp, Exception):
                raise resp
            return resp
    return _C


@pytest.fixture
def audio():
    return np.zeros(16000, dtype=np.float32)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    from backend.server.config import settings
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "groq_stt_prompt", "")


def test_happy_path_returns_the_transcript(monkeypatch, audio):
    import httpx
    monkeypatch.setattr(httpx, "Client", _client(_Resp()))
    assert stt_groq.transcribe_array(audio)["text"] == "open notepad"


@pytest.mark.parametrize("failure", [
    _Resp(status=429, text="rate limited"),
    _Resp(status=500, text="boom"),
    ConnectionError("network down"),
])
def test_any_failure_falls_back_to_gemini(monkeypatch, audio, failure):
    """429, 5xx and a dead socket must all demote rather than raise."""
    import httpx
    monkeypatch.setattr(httpx, "Client", _client(failure))
    called = {}

    def _fake(arr, sr=16000):
        called["yes"] = True
        return {"text": "from gemini", "language": "en",
                "language_probability": 1.0, "duration_sec": 1.0}

    from backend.ai_modules.speech import stt_gemini
    monkeypatch.setattr(stt_gemini, "transcribe_array", _fake)

    out = stt_groq.transcribe_array(audio)
    assert called.get("yes"), "Groq failure must fall back, not raise"
    assert out["text"] == "from gemini"


def test_missing_key_is_an_honest_failure(monkeypatch, audio):
    """No key is a misconfiguration, not a transcript. It must reach the
    spoken notice rather than silently costing Gemini quota."""
    from backend.server.config import settings
    monkeypatch.setattr(settings, "groq_api_key", "")
    with pytest.raises(SttUnavailable) as e:
        stt_groq.transcribe_array(audio)
    assert e.value.kind == "no_key"


def test_empty_audio_short_circuits(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "Client",
                        _client(RuntimeError("must not be called")))
    assert stt_groq.transcribe_array(np.zeros(0, dtype=np.float32))["text"] == ""


def test_prompt_is_omitted_when_unset_not_sent_empty():
    """An empty prompt string is not the same request as no prompt at all."""
    assert "prompt" not in stt_groq._payload()


def test_prompt_is_sent_when_configured(monkeypatch):
    from backend.server.config import settings
    monkeypatch.setattr(settings, "groq_stt_prompt", "Onyx, Razorpay")
    assert stt_groq._payload()["prompt"] == "Onyx, Razorpay"


def test_language_is_pinned_to_english():
    """Measured: without this the decoder drifted out of English entirely on
    quiet clips ('Var á ámurinn við í ætarið þeim?')."""
    assert stt_groq._payload()["language"] == "en"


def test_wav_encoding_is_16bit_mono(audio):
    import io
    import wave
    with wave.open(io.BytesIO(stt_groq._wav_bytes(audio, 16000))) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
