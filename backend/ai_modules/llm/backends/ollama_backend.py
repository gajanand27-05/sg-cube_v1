"""Ollama backend — wraps existing ollama_client for LLMProvider."""
from typing import Any, AsyncGenerator

from backend.ai_modules.llm import ollama_client
from backend.ai_modules.llm.provider import LLMBackend
from backend.server.config import settings


class OllamaBackend(LLMBackend):
    """Local Ollama backend for classification, reasoning, vision."""

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        json_mode: bool = False,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        return await ollama_client.generate(
            prompt, system=system, model=model, temperature=temperature, json_mode=json_mode, **kwargs
        )

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict, None]:
        async for chunk in ollama_client.chat_stream(
            messages, model=model, temperature=temperature, json_mode=json_mode, **kwargs
        ):
            yield chunk

    def embed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        return ollama_client.embed(text, model=model, **kwargs)

    async def aembed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        return await ollama_client.aembed(text, model=model, **kwargs)