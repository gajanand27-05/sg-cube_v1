"""Unified LLM Provider — single interface for all model backends.

Agents call `llm.generate()` / `llm.chat_stream()` / `llm.embed()`.
RoutingPolicy decides which backend handles the request.
"""
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from backend.ai_modules.llm.routing import RoutingPolicy, TaskType


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
        backend = self._get_backend(task)
        return await backend.generate(
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
        backend = self._get_backend(task)
        async for chunk in backend.chat_stream(
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