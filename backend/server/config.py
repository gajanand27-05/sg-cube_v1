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
    chat_model: str = "qwen/qwen3-coder-480b-a35b"  # openrouter
    
    # Vision
    vision_model: str = "qwen2.5vl:3b"          # local VLM
    
    # STT/TTS
    whisper_model: str = "small"                # faster-whisper
    piper_voice: str = "en_US-ryan-high"        # Piper TTS voice

    # ── OpenRouter (cloud LLM) ──
    openrouter_api_key: str = ""
    openrouter_model: str = "qwen/qwen3-coder-480b-a35b"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Gemini (Google AI SDK) ──
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ── Phase C3: LiveKit optional voice pipeline ──
    voice_pipeline: str = "local"  # "local" | "livekit"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""


settings = Settings()
