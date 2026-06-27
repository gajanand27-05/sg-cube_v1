"""Gemini chat-completion client via google-genai SDK."""
import asyncio
import logging

from google import genai

from backend.server.config import settings

log = logging.getLogger(__name__)


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def _map_messages(messages: list[dict]):
    """Convert OpenAI-format messages to Gemini contents list."""
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


async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    **_,
):
    """Stream tokens from Gemini (async generator).

    Yields dicts: {"token": str, "done": bool}.
    Expects messages in OpenAI format — converts system/config roles.
    """
    model = model or settings.gemini_model
    client = _client()
    system, mapped = _map_messages(messages)
    config = {"system_instruction": system, "temperature": temperature} if system else {"temperature": temperature}

    queue: asyncio.Queue = asyncio.Queue()

    def _run():
        for chunk in client.models.generate_content_stream(model=model, contents=mapped, config=config):
            queue.put_nowait(chunk.text or "")
        queue.put_nowait(None)

    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, _run)

    while True:
        text = await queue.get()
        if text is None:
            break
        yield {"token": text, "done": False}
    yield {"token": "", "done": True}
    await task


def generate(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    **_,
) -> str:
    """Non-streaming text generation."""
    model = model or settings.gemini_model
    client = _client()
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    config = {"temperature": temperature}
    if system:
        config["system_instruction"] = system

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        return response.text.strip()
    except Exception:
        log.exception("Gemini generate failed")
        return ""
