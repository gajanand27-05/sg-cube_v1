import httpx

from backend.server.config import settings


class OllamaError(RuntimeError):
    pass


def generate(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    timeout: float = 60.0,
) -> str:
    """Call Ollama /api/generate and return the response string.

    json_mode=True passes Ollama's `format: "json"` flag — the model is
    constrained to emit a syntactically-valid JSON object.
    """
    payload: dict = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"

    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
    except httpx.RequestError as e:
        raise OllamaError(
            f"Cannot reach Ollama at {settings.ollama_url}. Is `ollama serve` running? ({e})"
        ) from e

    if r.status_code != 200:
        raise OllamaError(f"Ollama returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    response = body.get("response")
    if response is None:
        raise OllamaError(f"Ollama response missing 'response' field: {body}")
    return response


def embed(text: str, timeout: float = 30.0) -> list[float]:
    """Call Ollama /api/embeddings and return the vector."""
    payload = {
        "model": settings.embedding_model,
        "prompt": text,
    }
    url = f"{settings.ollama_url.rstrip('/')}/api/embeddings"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
    except httpx.RequestError as e:
        raise OllamaError(f"Cannot reach Ollama for embeddings: {e}") from e

    if r.status_code != 200:
        raise OllamaError(f"Ollama embedding failed ({r.status_code}): {r.text[:200]}")

    return r.json().get("embedding", [])
