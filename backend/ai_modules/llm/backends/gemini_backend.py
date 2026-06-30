"""Gemini backend — Google AI SDK."""
import asyncio
import logging
from typing import Any, AsyncGenerator

from google import genai

from backend.ai_modules.llm.provider import LLMBackend
from backend.server.config import settings

log = logging.getLogger(__name__)


class GeminiBackend(LLMBackend):
    """Gemini backend for reasoning, coding, chat."""

    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.default_model = settings.gemini_model

    def _map_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Convert OpenAI-format to Gemini contents."""
        system = None
        contents = messages
        if messages and messages[0].get("role") == "system":
            system = messages[0]["content"]
            contents = messages[1:]
        mapped = []
        for m in contents:
            role = "model" if m["role"] == "assistant" else "user"
            mapped.append({"role": role, "parts": [{"text": m["content"]}]})
        return system, mapped

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
        model = model or self.default_model
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        config = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if json_mode:
            config["response_mime_type"] = "application/json"

        try:
            resp = await asyncio.wait_for(
                self.client.models.generate_content_async(
                    model=model, contents=contents, config=config
                ),
                timeout=timeout,
            )
            return resp.text.strip()
        except Exception as e:
            log.exception("Gemini generate failed")
            raise

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
        model = model or self.default_model
        system, mapped = self._map_messages(messages)
        config = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if json_mode:
            config["response_mime_type"] = "application/json"

        queue: asyncio.Queue = asyncio.Queue()

        def _run():
            try:
                for chunk in self.client.models.generate_content_stream(
                    model=model, contents=mapped, config=config
                ):
                    queue.put_nowait(chunk.text or "")
                queue.put_nowait(None)
            except Exception as e:
                log.exception("Gemini stream error")
                queue.put_nowait(e)

        loop = asyncio.get_running_loop()
        task = loop.run_in_executor(None, _run)

        while True:
            item = await queue.get()
            if item is None:
                yield {"token": "", "done": True}
                break
            if isinstance(item, Exception):
                raise item
            if item:
                yield {"token": item, "done": False}

        await task

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Use Ollama for embeddings")

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError("Use Ollama for embeddings")