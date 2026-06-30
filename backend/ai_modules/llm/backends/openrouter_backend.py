"""OpenRouter backend — cloud LLMs via OpenAI-compatible API."""
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from backend.ai_modules.llm.provider import LLMBackend
from backend.server.config import settings

log = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {settings.openrouter_api_key}",
    "Content-Type": "application/json",
}


class OpenRouterBackend(LLMBackend):
    """OpenRouter backend for chat, reasoning, coding."""

    def __init__(self):
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.default_model = settings.openrouter_model

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
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=HEADERS)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

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
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=HEADERS) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        yield {"token": "", "done": True}
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield {"token": token, "done": False}

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("OpenRouter does not provide embeddings")

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("OpenRouter does not provide embeddings")