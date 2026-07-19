"""Ollama HTTP client — async generate, chat_stream, embed.

Used by: verifier, episodic summarizer, intent classifier, embeddings.

Serves both local Ollama and Ollama Cloud: same /api/chat wire format, so
the only differences are the host and a bearer token. Pass base_url/api_key
to target the cloud; omit them for local.

embed()/aembed() are deliberately local-only — the Ollama Cloud catalog has
no embedding models, so pointing them at the cloud would break ChromaDB.
"""
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from backend.server.config import settings

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


BASE_URL = settings.ollama_url.rstrip("/")


def _endpoint(base_url: str | None) -> str:
    """Resolve the host to call — explicit arg wins, else local Ollama."""
    return (base_url or settings.ollama_url).rstrip("/")


def _headers(api_key: str | None) -> dict[str, str]:
    """Ollama Cloud authenticates with a bearer token; local needs nothing."""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def generate(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.0,
    json_mode: bool = False,
    timeout: float = 30.0,
    images: list[str] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> str:
    """Non-streaming generation. Supports images for VLM."""
    model = model or settings.fast_model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    # Ollama's /api/chat expects `content` to be a string with images at the
    # message level (`images: [...]`), not a multimodal content array — the
    # array form returns 400 "cannot unmarshal array into ... content of type
    # string" on this Ollama version.
    user_msg: dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{_endpoint(base_url)}/api/chat", json=payload, headers=_headers(api_key)
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: float = 60.0,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> AsyncGenerator[dict, None]:
    """Streaming chat — yields {'token': str, 'done': bool}."""
    model = model or settings.fast_model
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", f"{_endpoint(base_url)}/api/chat", json=payload,
            headers=_headers(api_key),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "message" in data:
                    token = data["message"].get("content", "")
                    if token:
                        yield {"token": token, "done": False}
                if data.get("done"):
                    yield {"token": "", "done": True}
                    break


def embed(text: str, model: str | None = None, timeout: float = 10.0, **kwargs: Any) -> list[float]:
    """Synchronous embedding — used by ChromaDB embedding function."""
    model = model or settings.embedding_model
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{BASE_URL}/api/embeddings", json={"model": model, "prompt": text})
        r.raise_for_status()
        return r.json()["embedding"]


async def aembed(text: str, model: str | None = None, timeout: float = 10.0, **kwargs: Any) -> list[float]:
    """Async embedding."""
    model = model or settings.embedding_model
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{BASE_URL}/api/embeddings", json={"model": model, "prompt": text})
        r.raise_for_status()
        return r.json()["embedding"]