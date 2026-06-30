"""Ollama client for local LLM inference and embeddings.

Matches the interface expected by verifier.py, episodic.py, llm_layer.py, long_term.py.
"""
import asyncio
import logging
from typing import Any

import httpx

from backend.server.config import settings

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


async def generate(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.0,
    json_mode: bool = False,
    timeout: float = 30.0,
) -> str:
    """Non-streaming generation. Returns the response text."""
    model = model or settings.ollama_model
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise OllamaError(f"Ollama {e.response.status_code}: {e.response.text[:200]}") from e
        except Exception as e:
            raise OllamaError(f"Ollama request failed: {e}") from e

    data = resp.json()
    return (data.get("message", {}).get("content") or "").strip()


async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: float = 60.0,
):
    """Streaming generation. Yields dicts: {"token": str, "done": bool}."""
    model = model or settings.ollama_model
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise OllamaError(f"Ollama {resp.status_code}: {body[:200]}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    import json
                    chunk = json.loads(line)
                except Exception:
                    continue
                token = chunk.get("message", {}).get("content", "")
                done = chunk.get("done", False)
                if token:
                    yield {"token": token, "done": False}
                if done:
                    yield {"token": "", "done": True}
                    return


def embed(text: str, model: str | None = None) -> list[float]:
    """Synchronous embedding for ChromaDB (called from sync context)."""
    model = model or settings.embedding_model
    url = f"{settings.ollama_url.rstrip('/')}/api/embeddings"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"model": model, "prompt": text})
            resp.raise_for_status()
    except Exception as e:
        log.error(f"Embedding failed for '{text[:50]}...': {e}")
        return [0.0] * 768  # nomic-embed-text dimension
    return resp.json().get("embedding", [0.0] * 768)


async def aembed(text: str, model: str | None = None) -> list[float]:
    """Async embedding variant."""
    model = model or settings.embedding_model
    url = f"{settings.ollama_url.rstrip('/')}/api/embeddings"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json={"model": model, "prompt": text})
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Async embedding failed: {e}")
            return [0.0] * 768
        return resp.json().get("embedding", [0.0] * 768)