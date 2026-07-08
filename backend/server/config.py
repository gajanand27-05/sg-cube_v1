from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    ollama_url: str = "http://localhost:11434"
    
    # ── Model aliases (single source of truth for routing) ──
    # Fast local models
    fast_model: str = "phi3"                    # classification, verification, intent
    embedding_model: str = "nomic-embed-text"   # vector embeddings
    
    # Reasoning / coding models
    reasoning_model: str = "gemini-2.5-flash"   # planner, complex logic
    coding_model: str = "gemini-2.5-flash"      # code generation
    
    # General conversation
    chat_model: str = "deepseek/deepseek-chat"  # openrouter (aspirational — not currently read)

    # Vision
    vision_model: str = "qwen2.5vl:3b"          # local VLM

    # STT/TTS
    whisper_model: str = "small"                # faster-whisper
    piper_voice: str = "en_US-ryan-high"        # Piper TTS voice

    # ── OpenRouter (primary cloud LLM — DeepSeek V3 default) ──
    # DeepSeek V3 wins for this project: strong JSON, tool-use, chat quality,
    # cheapest of the frontier-tier open-source models. Kimi K2 and Qwen 3
    # are the runner-ups kept in reserve — swap OPENROUTER_MODEL in .env
    # to try them.
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-chat"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Gemini (Google AI SDK) ──
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ── Phase C3: LiveKit optional voice pipeline ──
    voice_pipeline: str = "local"  # "local" | "livekit"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # ── Background services (toggle each independently) ──
    enable_vision: bool = True      # passive screen glance every 5m
    enable_wake_word: bool = True   # mic listener for the wake phrase
    enable_clipboard: bool = True   # clipboard change tracking
    enable_telemetry: bool = True   # CPU/mem/disk broadcast to UI
    enable_watcher: bool = True     # proactive agent triggers

    # ── Wake word ──
    wake_phrase: str = "onyx"
    wake_capture_seconds: float = 2.5
    wake_device: int | None = None  # mic device index; None = system default

    # ── Capability tier gate (Phase 0 Part B) ──
    # When true, Guardian passes SYSTEM_WRITE tools without prompting the
    # user. DESTRUCTIVE tier ignores this flag — power state, deletion,
    # shell exec, external messages ALWAYS require confirmation.
    auto_confirm_system_write: bool = False


settings = Settings()
