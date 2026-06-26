"""OpenRouter chat-completion client.

OpenAI-compatible API, usable with any provider (OpenAI, Anthropic, Google, etc.).
"""
import json
import logging

import httpx

from backend.server.config import settings

log = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {settings.openrouter_api_key}",
    "Content-Type": "application/json",
}


class OpenRouterError(RuntimeError):
    pass


async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: float = 120.0,
):
    """Stream tokens from OpenRouter chat completion.

    Yields dicts: {"token": str, "done": bool}.
    """
    model = model or settings.openrouter_model
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=_HEADERS) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise OpenRouterError(f"OpenRouter returned {resp.status_code}: {body[:500]}")

            full = ""
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ").strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                full += token
                yield {"token": token, "done": False}

    yield {"token": "", "done": True}


def generate(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 120.0,
) -> str:
    """Non-streaming text generation. Returns empty string on error."""
    model = model or settings.openrouter_model
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=payload, headers=_HEADERS)
        r.raise_for_status()
    except Exception:
        log.exception("OpenRouter generate failed")
        return ""

    return (r.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
