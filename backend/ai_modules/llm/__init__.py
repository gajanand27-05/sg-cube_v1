"""LLM Provider initialization — wire backends based on available config."""
import logging

from backend.ai_modules.llm.provider import LLMProvider, get_llm, init_llm_provider
from backend.ai_modules.llm.routing import RoutingPolicy, TaskType, build_default_policy
from backend.ai_modules.llm.backends import (
    OllamaBackend,
    OllamaCloudBackend,
    GeminiBackend,
    MockBackend,
)
from backend.server.config import settings

log = logging.getLogger(__name__)


def create_llm_provider(test_mode: bool = False) -> LLMProvider:
    """Create and configure LLMProvider with all available backends."""
    policy = build_default_policy()
    provider = init_llm_provider(policy)

    # Always register Ollama (local, no API key needed)
    try:
        provider.register("ollama", OllamaBackend())
        provider.register("embedding", OllamaBackend())  # embeddings via ollama
        log.info("Registered Ollama backend")
    except Exception as e:
        log.warning(f"Ollama backend unavailable: {e}")

    # Register Ollama Cloud if API key present
    if settings.ollama_api_key:
        try:
            provider.register("ollama_cloud", OllamaCloudBackend())
            log.info("Registered Ollama Cloud backend (%s)", settings.ollama_cloud_model)
        except Exception as e:
            log.warning(f"Ollama Cloud backend unavailable: {e}")

    # Register Gemini if API key present
    if settings.gemini_api_key:
        try:
            provider.register("gemini", GeminiBackend())
            log.info("Registered Gemini backend")
        except Exception as e:
            log.warning(f"Gemini backend unavailable: {e}")

    # Test mode: register mock backend as fallback
    if test_mode:
        mock = MockBackend()
        for name in ["ollama", "ollama_cloud", "gemini", "embedding"]:
            if name not in provider._backends:
                provider.register(name, mock)
        log.info("Test mode: registered MockBackend as fallback")

    # Validate critical routes have backends
    _validate_routes(provider, policy)

    return provider


def _validate_routes(provider: LLMProvider, policy: RoutingPolicy) -> None:
    """Warn if any routed task lacks a backend."""
    for task in TaskType:
        backend_name = policy.select(task)
        if backend_name not in provider._backends and backend_name != "embedding":
            log.warning(f"No backend for {task.value} -> {backend_name}")


def get_provider() -> LLMProvider:
    """Get global provider instance (initializes on first call)."""
    try:
        return get_llm()
    except RuntimeError:
        return create_llm_provider()