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

    # ── Phase 4A: barge-in (interrupt TTS by speaking) ──
    # Uses RMS thresholding not full VAD because Silero can't distinguish
    # "TTS bleed through mic" from "user speech" — both look like speech.
    # RMS + debounce is the honest "good enough in a quiet room" mitigation.
    # If the speaker is loud and near the mic, expect occasional false-fires.
    # True acoustic echo cancellation is future work — see docs/OPEN_TICKETS.md.
    enable_barge_in: bool = True
    barge_in_rms_threshold: float = 800.0  # int16 amplitude scale; ambient ~50-200, speech ~1500-3000
    barge_in_debounce_frames: int = 2  # consecutive high-RMS chunks required (~250ms at 125ms/chunk)

    # ── Capability tier gate ──
    # Phase 0.6 retired the global AUTO_CONFIRM_SYSTEM_WRITE flag in favor
    # of a per-tool trusted allowlist declared on each @tool. Legacy env
    # values (AUTO_CONFIRM_SYSTEM_WRITE=true) are silently ignored via
    # model_config extra="ignore" — no auto-approve happens on the
    # untrusted state-changing tools anymore.

    # ── Phase 2: Playwright browser automation ──
    # ENABLE_BROWSER gates whether the browser_* tools register at all.
    # If false, browser tools are absent from REGISTRY; the one-shot
    # open_url / read_webpage still work. Browser is LAZY — the actual
    # Chromium process only launches on the first tool call.
    enable_browser: bool = True
    browser_headless: bool = False  # visible window by default — desktop assistant, user wants to see it
    browser_profile_dir: str = "~/sg_cube/browser_profile"  # persistent context; outside repo
    browser_nav_timeout_ms: int = 30_000
    browser_action_timeout_ms: int = 10_000

    # ── Phase 3: data-source providers (all no-key by default) ──
    # If a provider is set to a keyed variant and the key is missing, the
    # tool returns a structured "not configured" result — never crashes.
    # Defaults use free public APIs so a fresh clone runs test-clean.
    stock_provider: str = "yahoo"      # "yahoo" (no key) | "finnhub"
    finnhub_api_key: str = ""
    weather_provider: str = "open-meteo"  # "open-meteo" (no key) | "openweather"
    openweather_api_key: str = ""
    news_api_key: str = ""             # optional; RSS default needs no key


settings = Settings()
