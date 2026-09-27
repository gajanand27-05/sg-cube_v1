"""Groq chat (OpenAI-compatible /chat/completions, streamed).

Registered as "groq" when GROQ_API_KEY is set, but no route uses it unless
routing says so: today it exists for tools/planner_bench.py to measure Groq's
models on the planner's own prompt. The same key already carries speech-to-
text, so the free tier's limits (per model: 30 req/min, 1,000/day, 8,000
tokens/min, 200,000 tokens/day) are shared with nothing else here.

`last_usage` holds the provider's own counts for the most recent stream
(prompt/completion tokens), since the prompt size is what the free tier
meters.
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from backend.ai_modules.llm.provider import LLMBackend
from backend.server.config import settings

_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqBackend(LLMBackend):
    def __init__(self, default_model: str | None = None):
        self.default_model = default_model or settings.groq_llm_model
        self.last_usage: dict = {}

    def _payload(self, messages, model, temperature, json_mode, stream) -> dict:
        payload: dict[str, Any] = {"model": model or self.default_model, "messages": messages,
                                   "temperature": temperature, "stream": stream}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if settings.groq_reasoning_effort:
            payload["reasoning_effort"] = settings.groq_reasoning_effort
        return payload

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.groq_api_key}"}

    async def generate(self, prompt: str, *, system: str = "", temperature: float = 0.0,
                       json_mode: bool = False, model: str | None = None, **kwargs: Any) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(_URL, headers=self._headers(),
                                  json=self._payload(messages, model, temperature, json_mode, False))
            r.raise_for_status()
            body = r.json()
        self.last_usage = body.get("usage") or {}
        return body["choices"][0]["message"].get("content") or ""

    async def chat_stream(self, messages: list[dict], *, temperature: float = 0.2,
                          json_mode: bool = False, model: str | None = None,
                          **kwargs: Any) -> AsyncGenerator[dict, None]:
        self.last_usage = {}
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", _URL, headers=self._headers(),
                                     json=self._payload(messages, model, temperature, json_mode, True)) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise httpx.HTTPStatusError(f"Groq {resp.status_code}: {resp.text[:300]}",
                                                request=resp.request, response=resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                    if usage:
                        self.last_usage = usage
                    for choice in chunk.get("choices") or []:
                        token = (choice.get("delta") or {}).get("content")
                        if token:  # reasoning text (gpt-oss) is not content: never spoken
                            yield {"token": token, "done": False}
        yield {"token": "", "done": True}

    def active_model_name(self) -> str | None:
        return self.default_model

    def embed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Groq provides no embedding models here")

    async def aembed(self, text: str, model: str | None = None, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Groq provides no embedding models here")
