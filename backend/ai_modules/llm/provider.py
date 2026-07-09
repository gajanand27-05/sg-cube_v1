"""Unified LLM Provider — single interface for all model backends.

Agents call `llm.generate()` / `llm.chat_stream()` / `llm.embed()`.
RoutingPolicy decides which backend handles the request. Phase 5B adds
provider-level fallback: on persistent failure of the selected backend,
retry once against `settings.llm_fallback_backend` (empty = no fallback).
"""
import logging
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


class LLMProvider:
    """Unified provider — routes requests to appropriate backend via RoutingPolicy."""

    def __init__(self, policy: RoutingPolicy | None = None):
        self.policy = policy or RoutingPolicy()
        self._backends: dict[str, LLMBackend] = {}

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
        try:
            return await primary.generate(
                prompt, system=system, temperature=temperature, json_mode=json_mode, **kwargs
            )
        except Exception as e:
            fallback = self._get_fallback_backend(primary_name)
            if fallback is None:
                raise
            fb_name, fb_backend = fallback
            _emit_fallback(primary_name, fb_name, str(e)[:200])
            log.warning("LLM primary '%s' failed (%s); falling over to '%s'",
                        primary_name, type(e).__name__, fb_name)
            return await fb_backend.generate(
                prompt, system=system, temperature=temperature, json_mode=json_mode, **kwargs
            )

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

        # Try primary. Track whether we've yielded anything — once we have,
        # we can't retry safely so mid-stream failures propagate.
        yielded_any = False
        try:
            async for chunk in primary.chat_stream(
                messages, temperature=temperature, json_mode=json_mode, **kwargs
            ):
                yielded_any = True
                yield chunk
            return
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

        # Fallback path — outside the except so re-raise from fallback
        # propagates cleanly with the original chain intact.
        async for chunk in fb_backend.chat_stream(
            messages, temperature=temperature, json_mode=json_mode, **kwargs
        ):
            yield chunk

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