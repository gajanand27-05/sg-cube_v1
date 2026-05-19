"""Shared LLM helper for Phase 11e content tools.

Calls Ollama's `/api/generate` endpoint in plain-text mode (no JSON format
constraint) using `agent_model` (gemma4). Used by summarize / translate /
explain_code — anything that needs a freeform-prose response rather than the
structured tool-call JSON that the agent loop uses.
"""
import httpx

from backend.server.config import settings


def llm_generate(prompt: str, *, system: str = "", temperature: float = 0.3, timeout: float = 120.0) -> str:
    """Send `prompt` to the agent model and return its response as plain text.

    Returns an empty string on any error (caller decides how to surface that).
    """
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload: dict = {
        "model": settings.agent_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=payload)
        r.raise_for_status()
    except Exception:
        return ""

    return (r.json().get("response") or "").strip()
