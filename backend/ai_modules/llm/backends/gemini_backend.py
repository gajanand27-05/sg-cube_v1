"""Gemini backend — Google AI SDK."""
import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator

from google import genai
from google.genai import errors as genai_errors

from backend.ai_modules.llm.provider import LLMBackend
from backend.ai_modules.llm.key_pool import pool
from backend.core.events import get_bus
from backend.daemon.ui_events import ProviderDegradedEvent
from backend.server.config import settings

log = logging.getLogger(__name__)


def _parse_gemini_retry_after(err: Exception, fallback: float) -> float:
    """Pull the retryDelay hint out of a Gemini 429 error body.

    Gemini surfaces the hint inside `details[].RetryInfo.retryDelay` as
    an ISO-ish string ("44s", "0.5s"). If we can't parse it, fall back
    to the configured backoff base.
    """
    body = str(err)
    m = re.search(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", body)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # Sometimes the body is JSON-shaped — try that too.
    try:
        # Very defensive: find the first {"error": ...} substring.
        start = body.find('{"error":')
        if start >= 0:
            info = json.loads(body[start:])
            for detail in info.get("error", {}).get("details", []):
                delay = detail.get("retryDelay")
                if isinstance(delay, str) and delay.endswith("s"):
                    return float(delay[:-1])
    except Exception:
        pass
    return fallback


def _is_gemini_retryable(err: Exception) -> tuple[bool, str]:
    """Return (retryable, reason). Retryable: 429 rate-limit or 5xx transient."""
    if isinstance(err, genai_errors.ClientError):
        # ClientError covers 4xx — only 429 is worth retrying.
        code = getattr(err, "code", None) or getattr(err, "status_code", None)
        if code == 429 or "429" in str(err) or "RESOURCE_EXHAUSTED" in str(err):
            return True, "429 rate-limited"
        return False, f"client error {code}"
    if isinstance(err, genai_errors.ServerError):
        return True, "5xx server error"
    if isinstance(err, asyncio.TimeoutError):
        return True, "timeout"
    return False, "non-retryable"


def _emit_degraded(reason: str, action: str, fallback: str = "") -> None:
    """Best-effort publish; never raises."""
    try:
        get_bus().publish(ProviderDegradedEvent(
            backend="gemini", reason=reason, action=action, fallback=fallback,
        ))
    except Exception:
        pass


class GeminiBackend(LLMBackend):
    """Gemini backend for reasoning, coding, chat."""

    def __init__(self):
        self.default_model = settings.gemini_model
        # Clients are built per call from the shared pool rather than pinned
        # here. A client constructed once in __init__ holds slot 1's key for
        # the life of the process, so a key parked by STT is still used by the
        # planner and vice versa — the two consumers each rediscover the same
        # dead key independently.
        self._clients: dict[int, genai.Client] = {}

    def _client_for_call(self) -> tuple[int, genai.Client] | None:
        """(slot, client) for the highest-priority unparked key, or None."""
        got = pool.acquire()
        if got is None:
            return None
        slot, key = got
        client = self._clients.get(slot)
        if client is None:
            client = genai.Client(api_key=key)
            self._clients[slot] = client
        return slot, client

    def _map_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Convert OpenAI-format to Gemini contents."""
        system = None
        contents = messages
        if messages and messages[0].get("role") == "system":
            system = messages[0]["content"]
            contents = messages[1:]
        mapped = []
        for m in contents:
            role = "model" if m["role"] == "assistant" else "user"
            mapped.append({"role": role, "parts": [{"text": m["content"]}]})
        return system, mapped

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.3,
        json_mode: bool = False,
        model: str | None = None,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> str:
        model = model or self.default_model
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        config = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if json_mode:
            config["response_mime_type"] = "application/json"

        max_retries = settings.llm_max_retries
        for attempt in range(1, max_retries + 1):
            got = self._client_for_call()
            if got is None:
                _emit_degraded("all keys parked", "gave_up")
                log.error("Gemini: every API key is parked; cannot generate")
                raise RuntimeError("all Gemini API keys are parked")
            slot, client = got
            try:
                # `client.aio.models` is the async surface in google-genai.
                # This used to call `client.models.generate_content_async`,
                # which is the OLD google-generativeai SDK's name and does not
                # exist here — every call raised AttributeError, which
                # _is_gemini_retryable classes as non-retryable, so the turn
                # died outright. The unit tests only covered the retry helpers,
                # never this call, so it stayed green while dead.
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    ),
                    timeout=timeout,
                )
                pool.report_success(slot)
                return resp.text.strip()
            except Exception as e:
                pool.report_failure(slot, e)
                retryable, reason = _is_gemini_retryable(e)
                if not retryable or attempt >= max_retries:
                    if retryable:
                        _emit_degraded(reason, "gave_up")
                    log.exception("Gemini generate failed (attempt %d/%d, reason=%s)",
                                  attempt, max_retries, reason)
                    raise
                wait = _parse_gemini_retry_after(e, settings.llm_backoff_base_s * attempt)
                log.warning("Gemini generate %s, retrying in %.1fs (attempt %d/%d)",
                            reason, wait, attempt, max_retries)
                _emit_degraded(reason, "retry")
                await asyncio.sleep(wait)

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        model: str | None = None,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> AsyncGenerator[dict, None]:
        model = model or self.default_model
        system, mapped = self._map_messages(messages)
        config = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if json_mode:
            config["response_mime_type"] = "application/json"

        max_retries = settings.llm_max_retries
        # Retry loop only wraps the pre-first-chunk phase. Once we've
        # yielded a token to the caller we cannot restart — mid-stream
        # failures propagate up unchanged.
        for attempt in range(1, max_retries + 1):
            got = self._client_for_call()
            if got is None:
                _emit_degraded("all keys parked", "gave_up")
                log.error("Gemini: every API key is parked; cannot chat_stream")
                raise RuntimeError("all Gemini API keys are parked")
            slot, client = got
            queue: asyncio.Queue = asyncio.Queue()

            def _run(client=client, slot=slot):
                try:
                    for chunk in client.models.generate_content_stream(
                        model=model, contents=mapped, config=config
                    ):
                        queue.put_nowait(chunk.text or "")
                    queue.put_nowait(None)
                    pool.report_success(slot)
                except Exception as e:
                    log.exception("Gemini stream error")
                    pool.report_failure(slot, e)
                    queue.put_nowait(e)

            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, _run)

            first = await queue.get()
            if isinstance(first, Exception):
                retryable, reason = _is_gemini_retryable(first)
                if not retryable or attempt >= max_retries:
                    if retryable:
                        _emit_degraded(reason, "gave_up")
                    await task  # let the executor settle
                    raise first
                wait = _parse_gemini_retry_after(first, settings.llm_backoff_base_s * attempt)
                log.warning("Gemini stream %s, retrying in %.1fs (attempt %d/%d)",
                            reason, wait, attempt, max_retries)
                _emit_degraded(reason, "retry")
                await task
                await asyncio.sleep(wait)
                continue

            # First chunk was clean — from here we can't retry safely.
            if first is None:
                yield {"token": "", "done": True}
                await task
                return
            if first:
                yield {"token": first, "done": False}

            while True:
                item = await queue.get()
                if item is None:
                    yield {"token": "", "done": True}
                    break
                if isinstance(item, Exception):
                    raise item
                if item:
                    yield {"token": item, "done": False}
            await task
            return

    def active_model_name(self) -> str | None:
        # Without this the base class returns None and _model_label falls back
        # to the ROUTING KEY, so the HUD's MODEL row read "gemini" instead of
        # "gemini-2.5-flash" — the exact regression active_model_name was added
        # to fix for Ollama, never implemented here.
        return self.default_model

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Use Ollama for embeddings")

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Use Ollama for embeddings")