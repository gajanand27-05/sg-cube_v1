"""Shared LLM helper for content tools (summarize / translate / explain_code).

Routes through RoutingPolicy like everything else, rather than naming a
backend. It used to call gemini_client.generate() directly, which broke every
caller once the stack moved off Gemini: with no GEMINI_API_KEY set,
summarize_url / summarize_pdf / explain_code / translate all returned
"No API key was provided" — four tools dead, and nothing failed at import time
to say so.

Deliberately synchronous. These tools are sync functions, so runtime.run_tool
hands them to run_in_executor; spinning up an event loop in that thread is the
exact pattern ollama_client.generate_sync exists to avoid (a thread-local
ProactorEventLoop hung nondeterministically next to uvicorn's own loop on
Windows/Py3.12). So resolve the backend from the policy and make the blocking
call ourselves.
"""
import logging

from backend.ai_modules.llm.ollama_client import generate_sync
from backend.ai_modules.llm.routing import TaskType, build_default_policy
from backend.server.config import settings

log = logging.getLogger(__name__)


def llm_generate(prompt: str, *, system: str = "", temperature: float = 0.3,
                 timeout: float = 120.0, task: TaskType = TaskType.SUMMARIZATION) -> str:
    """Send `prompt` to whichever backend RoutingPolicy picks for `task`, and
    return plain text.

    `task` defaults to SUMMARIZATION (local): condensing text the caller
    already fetched is what the small local model is for. Callers whose output
    is the user's actual answer — not a condensation — should pass a
    reasoning-class task so the routing policy sends it to the cloud model.

    Returns empty string on error (caller decides how to surface that).
    """
    backend = build_default_policy().select(task)

    if backend == "ollama_cloud":
        model = settings.ollama_cloud_model
        base_url = settings.ollama_cloud_url
        api_key = settings.ollama_api_key
    else:
        # Local, or a backend with no sync path of its own — either way the
        # local daemon can serve it. Named explicitly so a future backend
        # can't silently inherit local settings.
        if backend not in ("ollama", "mock"):
            log.warning("no sync path for backend %r; using local Ollama", backend)
        model = settings.fast_model
        base_url = None
        api_key = None

    try:
        return generate_sync(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            timeout=timeout,
            base_url=base_url,
            api_key=api_key,
        )
    except Exception as e:
        log.warning("llm_generate failed on backend %r: %s", backend, e)
        return ""
