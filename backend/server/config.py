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
    ollama_model: str = "phi3"  # fast intent classifier (cache/rule-miss path)
    agent_model: str = "gemma4:e4b-it-q8_0"  # heavier tool-calling agent
    embedding_model: str = "nomic-embed-text"
    vlm_model: str = "qwen2.5-vl"
    whisper_model: str = "small"  # ~half the WER of "base" with VAD/greedy keeping latency ~1s


settings = Settings()
