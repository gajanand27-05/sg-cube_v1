"""Shared LLM helper for content tools (summarize / translate / explain_code).

Uses Gemini cloud model.
"""
from backend.ai_modules.llm import gemini_client


def llm_generate(prompt: str, *, system: str = "", temperature: float = 0.3, timeout: float = 120.0) -> str:
    """Send `prompt` to the cloud model and return plain text.

    Returns empty string on error (caller decides how to surface that).
    """
    return gemini_client.generate(prompt, system=system, temperature=temperature)
