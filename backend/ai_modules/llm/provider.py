"""Unified LLM Provider — single interface for all model backends.

Agents call `llm.generate()` / `llm.chat_stream()` / `llm.embed()`.
RoutingPolicy decides which backend handles the request. Phase 5B adds
provider-level fallback: on persistent failure of the selected backend,
retry once against `settings.llm_fallback_backend` (empty = no fallback).
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from backend.ai_modules.llm.routing import RoutingPolicy, TaskType

log = logging.getLogger(__name__)


def _emit_fallback(from_backend: str, to_backend: str, reason: str) -> None:
    """Best-effort: publish a ProviderDegradedEvent(action="fallback")."""
    try:
        from backend.core.events import get_bus
        from backend.daemon.ui_events import ProviderDegradedEvent
        get_bus().publish(ProviderDegradedEvent(
            backend=from_backend, reason=reason,
            action="fallback", fallback=to_backend,
        ))
    except Exception:
        pass


def _model_label(backend: Any, registered_name: str) -> str:
    """Concrete model name for telemetry, falling back to the routing key.

    getattr rather than a direct call because active_model_name is an
    optional part of the interface and register() accepts any duck-typed
    object. A backend that doesn't implement it should degrade to reporting
    the routing key, not raise mid-request.
    """
    getter = getattr(backend, "active_model_name", None)
    if getter is None:
        return registered_name
    try:
        return getter() or registered_name
    except Exception:
        return registered_name


class LLMBackend(ABC):
    """Backend interface — each provider implements this."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str: ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[dict, None]: ...

    @abstractmethod
    def embed(self, text: str, **kwargs: Any) -> list[float]: ...

    @abstractmethod
    async def aembed(self, text: str, **kwargs: Any) -> list[float]: ...

    def active_model_name(self) -> str | None:
        """Concrete model this backend will actually call, for telemetry.

        Not abstract: a backend that can't say returns None and the caller
        falls back to the registered backend name. Without this, ai_metrics
        reported the routing key ("ollama_cloud") in active_model, so the UI's
        MODEL row named the backend rather than the model.
        """
        return None


class LLMProvider:
    """Unified provider — routes requests to appropriate backend via RoutingPolicy."""

    def __init__(self, policy: RoutingPolicy | None = None):
        self.policy = policy or RoutingPolicy()
        self._backends: dict[str, LLMBackend] = {}
        self._inflight = 0
        self._calls = 0

    def register(self, name: str, backend: LLMBackend) -> None:
        self._backends[name] = backend

    def _get_backend(self, task: TaskType) -> LLMBackend:
        backend_name = self.policy.select(task)
        if backend_name not in self._backends:
            raise RuntimeError(f"Backend '{backend_name}' not registered. Available: {list(self._backends)}")
        return self._backends[backend_name]

    def _get_fallback_backend(self, primary_name: str) -> tuple[str, LLMBackend] | None:
        """Phase 5B: pick a fallback backend if one is configured, distinct
        from `primary_name`, and actually registered. Returns (name, backend)
        or None."""
        from backend.server.config import settings
        fb_name = (settings.llm_fallback_backend or "").strip()
        if not fb_name or fb_name == primary_name:
            return None
        if fb_name not in self._backends:
            log.warning("llm_fallback_backend='%s' not registered; skipping fallback", fb_name)
            return None
        return fb_name, self._backends[fb_name]

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        task: TaskType = TaskType.GENERAL,
        temperature: float = 0.0,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str:
        primary_name = self.policy.select(task)
        if primary_name not in self._backends:
            raise RuntimeError(f"Backend '{primary_name}' not registered. Available: {list(self._backends)}")
        primary = self._backends[primary_name]
        self._inflight += 1
        self._calls += 1
        t0 = time.monotonic()
        model = _model_label(primary, primary_name)
        result = ""
        try:
            result = await primary.generate(
                prompt, system=system, temperature=temperature, json_mode=json_mode, **kwargs
            )
        except Exception as e:
            fallback = self._get_fallback_backend(primary_name)
            if fallback is None:
                self._inflight -= 1
                raise
            fb_name, fb_backend = fallback
            _emit_fallback(primary_name, fb_name, str(e)[:200])
            log.warning("LLM primary '%s' failed (%s); falling over to '%s'",
                        primary_name, type(e).__name__, fb_name)
            result = await fb_backend.generate(
                prompt, system=system, temperature=temperature, json_mode=json_mode, **kwargs
            )
            model = _model_label(fb_backend, fb_name)
        finally:
            latency_ms = (time.monotonic() - t0) * 1000
            self._inflight -= 1
        self._emit_metrics(model, result, latency_ms)
        return result

    def _emit_metrics(self, model: str, result: str, latency_ms: float) -> None:
        """Publish AIMetricsEvent — single source of truth for live telemetry.

        latency_ms is measured; tokens/s is estimated from actual output
        length (no provider token counts plumbed through yet). queue_depth is
        the real in-flight count; tool_calls is the cumulative generate count.
        """
        try:
            est_tokens = max(1, len(result) // 4)
            tps = est_tokens / (latency_ms / 1000) if latency_ms > 0 else 0.0
            from backend.core.events import get_bus
            from backend.daemon.ui_events import AIMetricsEvent
            get_bus().publish(AIMetricsEvent(
                tokens_per_second=round(tps, 1),
                latency_ms=round(latency_ms, 1),
                inference_ms=round(latency_ms, 1),
                queue_depth=self._inflight,
                tool_calls=self._calls,
                active_model=model,
            ))
        except Exception:
            pass

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        task: TaskType = TaskType.GENERAL,
        temperature: float = 0.2,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[dict, None]:
        primary_name = self.policy.select(task)
        if primary_name not in self._backends:
            raise RuntimeError(f"Backend '{primary_name}' not registered. Available: {list(self._backends)}")
        primary = self._backends[primary_name]

        # Metrics are accumulated here rather than only in generate(). The
        # Planner streams exclusively, so with the emit living only on the
        # generate() path ai_metrics never fired for the agent at all — the
        # UI's Model / Tok/s / Latency / Infer rows stayed empty forever and
        # the status pill could never leave Standby.
        self._inflight += 1
        self._calls += 1
        t0 = time.monotonic()
        accumulated = ""
        model = _model_label(primary, primary_name)
        completed = False

        # Try primary. Track whether we've yielded anything — once we have,
        # we can't retry safely so mid-stream failures propagate.
        yielded_any = False
        try:
            try:
                async for chunk in primary.chat_stream(
                    messages, temperature=temperature, json_mode=json_mode, **kwargs
                ):
                    yielded_any = True
                    accumulated += chunk.get("token") or ""
                    yield chunk
                completed = True
            except Exception as e:
                if yielded_any:
                    # Half-drained stream — can't recover, caller has to handle.
                    raise
                fallback = self._get_fallback_backend(primary_name)
                if fallback is None:
                    raise
                fb_name, fb_backend = fallback
                _emit_fallback(primary_name, fb_name, str(e)[:200])
                log.warning("LLM primary '%s' stream failed pre-yield (%s); falling over to '%s'",
                            primary_name, type(e).__name__, fb_name)
                model = _model_label(fb_backend, fb_name)

            if not completed:
                # Fallback path — outside the except so re-raise from fallback
                # propagates cleanly with the original chain intact.
                async for chunk in fb_backend.chat_stream(
                    messages, temperature=temperature, json_mode=json_mode, **kwargs
                ):
                    accumulated += chunk.get("token") or ""
                    yield chunk
                completed = True
        finally:
            self._inflight -= 1
            # One event per completed stream, never per chunk. Skipped on
            # failure so a dead stream doesn't report as throughput.
            if completed:
                self._emit_metrics(
                    model, accumulated, (time.monotonic() - t0) * 1000
                )

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        # Embeddings always use the embedding backend
        backend = self._backends.get("embedding")
        if not backend:
            raise RuntimeError("No embedding backend registered")
        return backend.embed(text, **kwargs)

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        backend = self._backends.get("embedding")
        if not backend:
            raise RuntimeError("No embedding backend registered")
        return await backend.aembed(text, **kwargs)


# Global instance — initialized at startup
llm: LLMProvider | None = None


def init_llm_provider(policy: RoutingPolicy | None = None) -> LLMProvider:
    global llm
    llm = LLMProvider(policy)
    return llm


def get_llm() -> LLMProvider:
    if llm is None:
        raise RuntimeError("LLM provider not initialized. Call init_llm_provider() first.")
    return llm