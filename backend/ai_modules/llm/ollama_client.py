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
import time
from typing import Any, AsyncGenerator

import httpx

from backend.server.config import settings

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


BASE_URL = settings.ollama_url.rstrip("/")

# ── embedding availability breaker ───────────────────────────────────────
#
# Measured 2026-08-13 with local Ollama stopped: a single httpx POST to a
# refused 127.0.0.1:11434 takes ~2.18s on Windows. Not our retries and not
# Chroma — one TCP connect, which Windows retransmits rather than failing on
# the first RST. ContextBuilder.collect() makes two embed calls per turn (LTM
# + visual), so every voice turn paid ~4.3s of dead time before the planner
# even started, and the only symptom was an assistant that felt broken.
#
# Two guards, because either alone leaves most of the cost:
#   * EMBED_CONNECT_TIMEOUT_S caps the connect attempt itself. Local Ollama
#     answers a loopback connect in single-digit ms or is not running.
#   * the breaker skips the attempt entirely for a short cooldown after a
#     connection failure, so a whole turn costs nothing rather than 2x the
#     connect timeout.
#
# Deliberately short cooldown: Ollama is usually restarted by hand while the
# assistant runs, and a sticky breaker would keep memory dead long after the
# backend came back. Only CONNECTION failures trip it — an HTTP error means
# something IS listening, and that is a different problem.
EMBED_CONNECT_TIMEOUT_S = 0.5
EMBED_BREAKER_COOLDOWN_S = 5.0
_embed_down_until: float = 0.0


def _is_local(url: str) -> bool:
    return "127.0.0.1" in url or "localhost" in url or "://[::1]" in url


def _timeout_for(url: str, timeout: float) -> httpx.Timeout:
    """Read timeout as asked; connect timeout short only for LOCAL Ollama.

    A loopback connect either lands in single-digit ms or there is nothing
    listening — but the cloud is over the internet, where half a second is a
    perfectly ordinary handshake. Applying the local figure to both would turn
    a slow network into an outage.
    """
    if not _is_local(url):
        return httpx.Timeout(timeout)
    return httpx.Timeout(timeout, connect=EMBED_CONNECT_TIMEOUT_S)


def _embed_timeout(timeout: float) -> httpx.Timeout:
    return _timeout_for(BASE_URL, timeout)


def _embed_breaker_open() -> bool:
    return time.monotonic() < _embed_down_until


def _note_embed_failure() -> None:
    global _embed_down_until
    _embed_down_until = time.monotonic() + EMBED_BREAKER_COOLDOWN_S


def _note_embed_success() -> None:
    global _embed_down_until
    _embed_down_until = 0.0


def reset_embed_breaker() -> None:
    """Clear the cooldown — for tests, and for a caller that knows better."""
    _note_embed_success()


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

    endpoint = _endpoint(base_url)
    async with httpx.AsyncClient(timeout=_timeout_for(endpoint, timeout)) as client:
        r = await client.post(
            f"{endpoint}/api/chat", json=payload, headers=_headers(api_key)
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


def generate_sync(
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
    """Blocking twin of generate() — for threads that must not touch an event
    loop (the vision loop's background thread under uvicorn: a thread-local
    ProactorEventLoop hung nondeterministically next to uvicorn's own proactor
    loop on Windows/Py3.12). Same wire format as the async twin."""
    model = model or settings.fast_model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
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

    endpoint = _endpoint(base_url)
    with httpx.Client(timeout=_timeout_for(endpoint, timeout)) as client:
        r = client.post(
            f"{endpoint}/api/chat", json=payload, headers=_headers(api_key)
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

    endpoint = _endpoint(base_url)
    async with httpx.AsyncClient(timeout=_timeout_for(endpoint, timeout)) as client:
        async with client.stream(
            "POST", f"{endpoint}/api/chat", json=payload,
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
    if _embed_breaker_open():
        raise httpx.ConnectError(
            f"embedding backend marked down for another "
            f"{_embed_down_until - time.monotonic():.1f}s (skipped without connecting)"
        )
    model = model or settings.embedding_model
    try:
        with httpx.Client(timeout=_embed_timeout(timeout)) as client:
            r = client.post(f"{BASE_URL}/api/embeddings", json={"model": model, "prompt": text})
            r.raise_for_status()
            vec = r.json()["embedding"]
    except (httpx.ConnectError, httpx.ConnectTimeout):
        _note_embed_failure()
        raise
    _note_embed_success()
    return vec


async def aembed(text: str, model: str | None = None, timeout: float = 10.0, **kwargs: Any) -> list[float]:
    """Async embedding. Shares the breaker with embed() — same backend."""
    if _embed_breaker_open():
        raise httpx.ConnectError(
            f"embedding backend marked down for another "
            f"{_embed_down_until - time.monotonic():.1f}s (skipped without connecting)"
        )
    model = model or settings.embedding_model
    try:
        async with httpx.AsyncClient(timeout=_embed_timeout(timeout)) as client:
            r = await client.post(f"{BASE_URL}/api/embeddings", json={"model": model, "prompt": text})
            r.raise_for_status()
            vec = r.json()["embedding"]
    except (httpx.ConnectError, httpx.ConnectTimeout):
        _note_embed_failure()
        raise
    _note_embed_success()
    return vec