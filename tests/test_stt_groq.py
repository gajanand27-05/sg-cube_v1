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
])
def test_service_errors_fall_back_to_gemini(monkeypatch, audio, failure):
    """A 429 or 5xx is Groq saying no, not the link being down, so Gemini is
    worth trying. Network errors take a different route — see
    test_network_error_skips_gemini_entirely."""
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


# ── The offline chain ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_memo():
    stt_groq._network_down_until = 0.0
    yield
    stt_groq._network_down_until = 0.0


def _local_returns(monkeypatch, text="volume up"):
    calls = []
    from backend.ai_modules.speech import stt_whisper
    monkeypatch.setattr(stt_whisper, "transcribe_array_cpu",
                        lambda a, sr=16000: calls.append("local") or
                        {"text": text, "language": "en",
                         "language_probability": 1.0, "duration_sec": 1.0})
    return calls


def test_network_error_skips_gemini_entirely(monkeypatch, audio):
    """Gemini is on the same dead network. Trying it buys nothing and costs a
    second full timeout of silence — 10-20s before 'volume up' works."""
    import httpx
    monkeypatch.setattr(httpx, "Client", _client(httpx.ConnectTimeout("timed out")))
    local = _local_returns(monkeypatch)

    from backend.ai_modules.speech import stt_gemini
    monkeypatch.setattr(stt_gemini, "transcribe_array",
                        lambda *a, **k: pytest.fail("Gemini must be skipped on a network error"))

    assert stt_groq.transcribe_array(audio)["text"] == "volume up"
    assert local == ["local"]


def test_http_error_still_tries_gemini(monkeypatch, audio):
    """A 429 is Groq's problem, not the link's — Gemini may well answer."""
    import httpx
    monkeypatch.setattr(httpx, "Client", _client(_Resp(status=429, text="rate limited")))
    seen = []
    from backend.ai_modules.speech import stt_gemini
    monkeypatch.setattr(stt_gemini, "transcribe_array",
                        lambda *a, **k: seen.append("gemini") or
                        {"text": "from gemini", "language": "en",
                         "language_probability": 1.0, "duration_sec": 1.0})
    assert stt_groq.transcribe_array(audio)["text"] == "from gemini"
    assert seen == ["gemini"]


def test_a_network_failure_is_remembered(monkeypatch, audio):
    """Only the FIRST offline command pays the cloud timeout."""
    import httpx
    attempts = []

    class _Counting(_client(httpx.ConnectError("no route"))):
        def post(self_inner, *a, **kw):
            attempts.append(1)
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "Client", _Counting)
    local = _local_returns(monkeypatch)

    for _ in range(3):
        stt_groq.transcribe_array(audio)

    assert len(attempts) == 1, "later commands must not re-try the dead cloud"
    assert local == ["local"] * 3


def test_the_memo_expires(monkeypatch, audio):
    import httpx
    monkeypatch.setattr(httpx, "Client", _client(_Resp()))
    stt_groq._network_down_until = 0.0
    assert stt_groq.transcribe_array(audio)["text"] == "open notepad"


def test_a_cloud_success_clears_the_memo(monkeypatch, audio):
    """The link coming back must stop short-circuiting to local."""
    import httpx
    import time as _t
    stt_groq._network_down_until = _t.monotonic() + 999
    monkeypatch.setattr(httpx, "Client", _client(_Resp()))
    released = []
    from backend.ai_modules.speech import stt_whisper
    monkeypatch.setattr(stt_whisper, "release_cpu_model",
                        lambda: released.append("released"))
    monkeypatch.setattr(stt_whisper, "transcribe_array_cpu",
                        lambda a, sr=16000: {"text": "local", "language": "en",
                                             "language_probability": 1.0,
                                             "duration_sec": 1.0})
    # still inside the memo -> local
    assert stt_groq.transcribe_array(audio)["text"] == "local"
    # force expiry, cloud answers, memo clears and the model is freed
    stt_groq._network_down_until = 1.0
    assert stt_groq.transcribe_array(audio)["text"] == "open notepad"
    assert stt_groq._network_down_until == 0.0
    assert released == ["released"]


def test_timeout_is_short_enough_for_a_voice_turn():
    from backend.server.config import settings
    assert settings.groq_timeout_s <= 3.0, (
        "a spoken command must not wait longer than this for a cloud that is "
        "not answering — the local fallback behind it needs ~8s cold")


def test_stt_facade_does_not_import_whisper_eagerly():
    """ctranslate2 is ~198 MiB resident and STT_BACKEND=groq never uses it."""
    import ast
    src = Path("backend/ai_modules/speech/stt.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.col_offset == 0:
            assert "stt_whisper" not in [a.name for a in node.names], (
                "stt_whisper must be imported lazily, inside the functions "
                "that actually use it")
