"""Ollama backends — local and cloud, both over the same /api/chat format."""
from typing import Any, AsyncGenerator

from backend.ai_modules.llm import ollama_client
from backend.ai_modules.llm.provider import LLMBackend
from backend.server.config import settings


class OllamaBackend(LLMBackend):
    """Local Ollama backend for classification, reasoning, vision.

    base_url/api_key/default_model default to local. OllamaCloudBackend
    subclasses this with the cloud host and a bearer token — the wire format
    is identical, so nothing else changes.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model

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
            prompt,
            system=system,
            model=model or self.default_model,
            temperature=temperature,
            json_mode=json_mode,
            base_url=self.base_url,
            api_key=self.api_key,
            **kwargs,
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
            messages,
            model=model or self.default_model,
            temperature=temperature,
            json_mode=json_mode,
            base_url=self.base_url,
            api_key=self.api_key,
            **kwargs,
        ):
            yield chunk

    def embed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        # Always local: the Ollama Cloud catalog has no embedding models.
        return ollama_client.embed(text, model=model, **kwargs)

    async def aembed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        return await ollama_client.aembed(text, model=model, **kwargs)


class OllamaCloudBackend(OllamaBackend):
    """Ollama Cloud — big hosted models (planner, coding, chat).

    Free tier meters GPU-time rather than tokens, so heavier models drain
    quota faster. Embeddings and vision deliberately stay on the local
    backend; only reasoning-class traffic belongs here.
    """

    def __init__(self):
        super().__init__(
            base_url=settings.ollama_cloud_url,
            api_key=settings.ollama_api_key,
            default_model=settings.ollama_cloud_model,
        )

    def embed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Ollama Cloud provides no embedding models")

    async def aembed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Ollama Cloud provides no embedding models")
