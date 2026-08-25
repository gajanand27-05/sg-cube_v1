"""Phase 5B — LLM provider failure resilience.

Two axes:
  * Gemini backend now detects 429 / 5xx / timeout and retries with
    server-directed backoff (parsed from the Gemini error body's
    retryDelay hint) or the configured base.
  * LLMProvider falls over to `settings.llm_fallback_backend` if the
    primary backend fails and (for chat_stream) hasn't yielded yet.

We mock the backends because the real Gemini/Ollama Cloud clients need
network + keys. Focus is the wrapper logic, not the SDKs.
"""
import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture(autouse=True)
def _restore_fallback_setting():
    """Snapshot and restore `llm_fallback_backend` around every test here.

    Several tests below set it and then restore it to a hardcoded "" in their
    `finally`. That was the default once; it is not any more, so those
    restores silently clobbered the real setting for every test that ran
    afterwards. Restoring to the value we actually found is the only version
    that stays correct when the default changes again.
    """
    from backend.server.config import settings
    original = settings.llm_fallback_backend
    try:
        yield
    finally:
        settings.llm_fallback_backend = original


# ── Gemini retry helpers ──────────────────────────────────────────────

def test_parse_gemini_retry_after_from_repr():
    from backend.ai_modules.llm.backends.gemini_backend import _parse_gemini_retry_after
    err_body = (
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
        "'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
        "'retryDelay': '44s'}]}}"
    )
    e = RuntimeError(err_body)
    assert _parse_gemini_retry_after(e, fallback=99.0) == 44.0
    print("  [PASS] retryDelay parsed from Gemini error body")


def test_parse_gemini_retry_after_fallback_when_unparseable():
    from backend.ai_modules.llm.backends.gemini_backend import _parse_gemini_retry_after
    e = RuntimeError("something totally unrelated")
    assert _parse_gemini_retry_after(e, fallback=7.5) == 7.5
    print("  [PASS] unparseable error falls back to configured base")


def test_is_gemini_retryable_429():
    from backend.ai_modules.llm.backends.gemini_backend import _is_gemini_retryable
    from google.genai import errors as genai_errors
    # ClientError is what the SDK raises on 4xx. We fabricate the shape.
    try:
        err = genai_errors.ClientError(429, {"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}}, response=None)
    except TypeError:
        # If the constructor signature changes across versions, fall back to a
        # duck-typed sentinel that carries what our function reads.
        err = type("FakeClientErr", (genai_errors.ClientError,), {})
        err = err.__new__(err)  # skip __init__
        err.code = 429
        err.args = ("429 RESOURCE_EXHAUSTED",)
    retryable, reason = _is_gemini_retryable(err)
    assert retryable, f"429 should be retryable, got reason={reason}"
    assert "429" in reason or "rate" in reason
    print(f"  [PASS] 429 identified as retryable ({reason})")


def test_is_gemini_retryable_timeout():
    from backend.ai_modules.llm.backends.gemini_backend import _is_gemini_retryable
    err = asyncio.TimeoutError()
    retryable, reason = _is_gemini_retryable(err)
    assert retryable
    assert "timeout" in reason
    print("  [PASS] TimeoutError identified as retryable")


def test_is_gemini_retryable_non_429_not_retried():
    from backend.ai_modules.llm.backends.gemini_backend import _is_gemini_retryable
    err = RuntimeError("some totally unrelated bug")
    retryable, reason = _is_gemini_retryable(err)
    assert not retryable
    print("  [PASS] unrelated errors are NOT retryable")


# ── SDK call-surface contract ─────────────────────────────────────────
# The tests above only exercise the retry HELPERS. They stayed green for the
# whole time GeminiBackend.generate called `client.models.generate_content_async`
# — a method of the OLD google-generativeai SDK that does not exist in
# google-genai. Every real Gemini generate() raised AttributeError, which
# _is_gemini_retryable classes as non-retryable, so the turn died outright.
# These two assert the attribute paths the backend actually calls exist on a
# real client object. No network: genai.Client() does not dial out on
# construction, and we never invoke the methods.

def _speccd_client():
    """A mock shaped by the REAL genai.Client — attributes the SDK does not
    have raise AttributeError, exactly as they did in production."""
    from unittest.mock import create_autospec
    from google import genai
    # Client() does not dial out on construction; nothing here hits the network.
    return create_autospec(genai.Client(api_key="dummy-key-not-used"), instance=True)


def _make_backend(client):
    from backend.ai_modules.llm.backends.gemini_backend import GeminiBackend
    with patch("google.genai.Client", return_value=client):
        return GeminiBackend()


def test_gemini_generate_calls_a_real_sdk_method():
    client = _speccd_client()
    client.aio.models.generate_content.return_value = type("R", (), {"text": " hi "})()

    be = _make_backend(client)
    out = asyncio.run(be.generate("ping", system="be brief", temperature=0.0))

    assert out == "hi", f"expected stripped text, got {out!r}"
    assert client.aio.models.generate_content.await_count == 1
    print("  [PASS] generate() drives client.aio.models.generate_content")


def test_gemini_reports_concrete_model_to_telemetry():
    """The HUD's MODEL row renders ai_metrics.active_model verbatim.

    GeminiBackend inherited the base active_model_name() -> None, so
    _model_label fell back to the ROUTING KEY and the HUD read "gemini"
    instead of "gemini-2.5-flash".
    """
    from backend.ai_modules.llm.provider import _model_label
    from backend.server.config import settings

    be = _make_backend(_speccd_client())
    label = _model_label(be, "gemini")
    assert label == settings.gemini_model, (
        f"telemetry should name the model, got {label!r}"
    )
    assert label != "gemini", "active_model must not be the routing key"
    print(f"  [PASS] telemetry reports {label!r}, not the routing key")


def test_gemini_chat_stream_calls_a_real_sdk_method():
    client = _speccd_client()
    client.models.generate_content_stream.return_value = iter(
        [type("C", (), {"text": "a"})(), type("C", (), {"text": "b"})()]
    )

    be = _make_backend(client)

    async def _drive():
        return [ev async for ev in be.chat_stream([{"role": "user", "content": "hi"}])]

    events = asyncio.run(_drive())

    assert [e["token"] for e in events if not e["done"]] == ["a", "b"]
    assert events[-1]["done"] is True
    assert client.models.generate_content_stream.call_count == 1
    print("  [PASS] chat_stream() drives client.models.generate_content_stream")


# ── LLMProvider fallback wiring ───────────────────────────────────────

class _FakeBackend:
    """Minimal LLMBackend stub. Records calls; can be scripted to raise."""

    def __init__(self, name: str, response: str = "primary reply", raises: Exception | None = None):
        self.name = name
        self.response = response
        self.raises = raises
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, prompt, **kw):
        self.generate_calls += 1
        if self.raises:
            raise self.raises
        return self.response

    async def chat_stream(self, messages, **kw) -> AsyncGenerator[dict, None]:
        self.stream_calls += 1
        if self.raises:
            raise self.raises
        yield {"token": self.response, "done": False}
        yield {"token": "", "done": True}

    def embed(self, text, **kw):
        return []

    async def aembed(self, text, **kw):
        return []


def _make_provider(primary_raises=None, fallback_name="fallback"):
    """Build an LLMProvider with a scripted primary and a clean fallback."""
    from backend.ai_modules.llm.provider import LLMProvider
    from backend.ai_modules.llm.routing import RoutingPolicy, TaskType
    policy = RoutingPolicy({t: "primary" for t in TaskType})
    p = LLMProvider(policy)
    primary = _FakeBackend("primary", response="from primary", raises=primary_raises)
    fallback = _FakeBackend(fallback_name, response="from fallback")
    p.register("primary", primary)
    p.register(fallback_name, fallback)
    return p, primary, fallback


def test_generate_no_failure_no_fallback():
    from backend.server.config import settings
    provider, primary, fallback = _make_provider(primary_raises=None)
    settings.llm_fallback_backend = "fallback"
    try:
        result = asyncio.run(provider.generate("hi"))
    finally:
        settings.llm_fallback_backend = ""
    assert result == "from primary"
    assert primary.generate_calls == 1
    assert fallback.generate_calls == 0
    print("  [PASS] generate: no failure → no fallback attempted")


def test_generate_fallback_configured_and_primary_fails():
    from backend.server.config import settings
    provider, primary, fallback = _make_provider(primary_raises=RuntimeError("429 RESOURCE_EXHAUSTED"))
    settings.llm_fallback_backend = "fallback"
    try:
        result = asyncio.run(provider.generate("hi"))
    finally:
        settings.llm_fallback_backend = ""
    assert result == "from fallback"
    assert primary.generate_calls == 1
    assert fallback.generate_calls == 1
    print("  [PASS] generate: primary fails + fallback configured → fallback called")


def test_generate_no_fallback_configured_reraises():
    from backend.server.config import settings
    provider, primary, fallback = _make_provider(primary_raises=RuntimeError("429"))
    settings.llm_fallback_backend = ""
    try:
        try:
            asyncio.run(provider.generate("hi"))
        except RuntimeError as e:
            assert "429" in str(e)
        else:
            assert False, "expected RuntimeError to propagate"
    finally:
        settings.llm_fallback_backend = ""
    assert fallback.generate_calls == 0
    print("  [PASS] generate: no fallback configured → primary error propagates")


def test_generate_fallback_same_as_primary_reraises():
    """Guard against infinite loop: fallback == primary must NOT self-invoke."""
    from backend.server.config import settings
    provider, primary, _ = _make_provider(primary_raises=RuntimeError("429"))
    settings.llm_fallback_backend = "primary"  # same as primary
    try:
        try:
            asyncio.run(provider.generate("hi"))
        except RuntimeError:
            pass
        else:
            assert False, "expected RuntimeError to propagate"
    finally:
        settings.llm_fallback_backend = ""
    assert primary.generate_calls == 1  # called once, not twice
    print("  [PASS] generate: fallback == primary → no self-fallback")


def test_generate_fallback_unregistered_reraises():
    from backend.server.config import settings
    provider, primary, _ = _make_provider(primary_raises=RuntimeError("429"))
    settings.llm_fallback_backend = "nonexistent_backend"
    try:
        try:
            asyncio.run(provider.generate("hi"))
        except RuntimeError:
            pass
        else:
            assert False, "expected propagate when fallback missing"
    finally:
        settings.llm_fallback_backend = ""
    print("  [PASS] generate: fallback name not registered → primary error propagates")


def test_chat_stream_fallback_on_pre_yield_failure():
    from backend.server.config import settings
    provider, primary, fallback = _make_provider(primary_raises=RuntimeError("429"))
    settings.llm_fallback_backend = "fallback"

    async def _drive():
        chunks = []
        async for c in provider.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(c)
        return chunks

    try:
        chunks = asyncio.run(_drive())
    finally:
        settings.llm_fallback_backend = ""
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 1
    assert any(c.get("token") == "from fallback" for c in chunks)
    print("  [PASS] chat_stream: pre-yield failure → fallback stream drained")


def test_chat_stream_mid_stream_failure_does_not_fallback():
    """Once primary has yielded any chunk, mid-stream failure must propagate."""
    from backend.ai_modules.llm.provider import LLMProvider
    from backend.ai_modules.llm.routing import RoutingPolicy, TaskType
    from backend.server.config import settings

    class _MidStreamFailure(_FakeBackend):
        async def chat_stream(self, messages, **kw):
            self.stream_calls += 1
            yield {"token": "first token from primary", "done": False}
            raise RuntimeError("mid-stream 5xx")

    policy = RoutingPolicy({t: "primary" for t in TaskType})
    provider = LLMProvider(policy)
    primary = _MidStreamFailure("primary")
    fallback = _FakeBackend("fallback")
    provider.register("primary", primary)
    provider.register("fallback", fallback)
    settings.llm_fallback_backend = "fallback"

    async def _drive():
        collected = []
        try:
            async for c in provider.chat_stream([{"role": "user", "content": "hi"}]):
                collected.append(c)
        except RuntimeError as e:
            return collected, str(e)
        return collected, None

    try:
        collected, err = asyncio.run(_drive())
    finally:
        settings.llm_fallback_backend = ""
    assert err is not None and "5xx" in err, f"expected mid-stream 5xx to propagate, got {err!r}"
    assert fallback.stream_calls == 0, "fallback must NOT be called after any yield"
    assert collected == [{"token": "first token from primary", "done": False}]
    print("  [PASS] chat_stream: mid-stream failure propagates, no fallback")


if __name__ == "__main__":
    test_parse_gemini_retry_after_from_repr()
    test_parse_gemini_retry_after_fallback_when_unparseable()
    test_is_gemini_retryable_429()
    test_is_gemini_retryable_timeout()
    test_is_gemini_retryable_non_429_not_retried()
    test_gemini_generate_calls_a_real_sdk_method()
    test_gemini_reports_concrete_model_to_telemetry()
    test_gemini_chat_stream_calls_a_real_sdk_method()
    test_generate_no_failure_no_fallback()
    test_generate_fallback_configured_and_primary_fails()
    test_generate_no_fallback_configured_reraises()
    test_generate_fallback_same_as_primary_reraises()
    test_generate_fallback_unregistered_reraises()
    test_chat_stream_fallback_on_pre_yield_failure()
    test_chat_stream_mid_stream_failure_does_not_fallback()
    print("All Phase 5B LLM resilience tests passed.")


# ── The failover must actually be ENABLED, not merely implemented ─────

def test_llm_fallback_backend_is_configured():
    """A 12-second network drop killed 12 consecutive commands in a live
    sweep — every one of them `[Errno 11001] getaddrinfo failed`, spoken as
    "Sorry, I encountered an error".

    provider.chat_stream has a complete, careful pre-yield failover: it
    catches, picks a fallback backend, emits telemetry and re-streams, and it
    correctly refuses to fail over once tokens have been yielded. None of it
    ran, because `llm_fallback_backend` defaulted to "" and
    _get_fallback_backend returns None on empty.

    Machinery that is built, tested and switched off is worth exactly nothing
    during the outage it was written for.
    """
    from backend.server.config import settings
    assert settings.llm_fallback_backend, (
        "llm_fallback_backend is empty — a cloud outage takes the assistant "
        "down entirely instead of degrading to the local model"
    )


def test_the_configured_fallback_backend_is_actually_registered():
    """_get_fallback_backend logs a warning and returns None for an
    unregistered name, which fails silently at exactly the wrong moment."""
    from backend.ai_modules.llm import create_llm_provider
    from backend.server.config import settings

    provider = create_llm_provider()
    assert settings.llm_fallback_backend in provider._backends, (
        f"fallback {settings.llm_fallback_backend!r} is not registered; "
        f"registered: {list(provider._backends)}"
    )


def test_the_fallback_runs_on_a_local_model():
    """The point of the fallback is surviving a network loss, so it must not
    be another cloud backend. It also must not silently inherit phi3
    (settings.fast_model), which the verifier uses and which is weak at the
    tool-call JSON the planner emits."""
    from backend.ai_modules.llm import create_llm_provider
    from backend.server.config import settings

    provider = create_llm_provider()
    backend = provider._backends[settings.llm_fallback_backend]
    base = (getattr(backend, "base_url", "") or "").lower()
    assert "127.0.0.1" in base or "localhost" in base, (
        f"fallback points at {base!r} — a cloud fallback cannot survive the "
        "outage it exists for"
    )
    assert getattr(backend, "default_model", None), (
        "fallback backend has no explicit model, so it inherits fast_model "
        "(phi3) — pin a capable local planner model instead"
    )
