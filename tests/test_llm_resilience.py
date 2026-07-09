"""Phase 5B — LLM provider failure resilience.

Two axes:
  * Gemini backend now detects 429 / 5xx / timeout and retries with
    server-directed backoff (parsed from the Gemini error body's
    retryDelay hint) or the configured base.
  * LLMProvider falls over to `settings.llm_fallback_backend` if the
    primary backend fails and (for chat_stream) hasn't yielded yet.

We mock the backends because the real Gemini/OpenRouter clients need
network + keys. Focus is the wrapper logic, not the SDKs.
"""
import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


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
    test_generate_no_failure_no_fallback()
    test_generate_fallback_configured_and_primary_fails()
    test_generate_no_fallback_configured_reraises()
    test_generate_fallback_same_as_primary_reraises()
    test_generate_fallback_unregistered_reraises()
    test_chat_stream_fallback_on_pre_yield_failure()
    test_chat_stream_mid_stream_failure_does_not_fallback()
    print("All Phase 5B LLM resilience tests passed.")
