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
    
    # Reasoning / coding models (served by Ollama Cloud — see below)
    reasoning_model: str = "gpt-oss:120b"  # planner, complex logic
    coding_model: str = "gpt-oss:120b"     # code generation

    # General conversation
    chat_model: str = "gpt-oss:120b"       # aspirational — not currently read

    # Vision
    vision_model: str = "qwen2.5vl:3b"          # local VLM

    # STT/TTS
    whisper_model: str = "small"                # faster-whisper
    piper_voice: str = "en_US-ryan-high"        # Piper TTS voice

    # ── Ollama Cloud (primary cloud LLM — gpt-oss:120b default) ──
    # Same /api/chat wire format as local Ollama, just a different host plus
    # a bearer token, so the local client serves both.
    #
    # NOTE: /api/tags is a PUBLIC endpoint and lists the whole catalog
    # regardless of entitlement. Most heavy models (deepseek-v4-flash/pro,
    # qwen3.5, glm-5.1, kimi-k2.5) return 403 "this model requires a
    # subscription" on the Free tier — do not pick a model from the catalog
    # without POSTing to /api/chat to confirm access.
    #
    # Measured on Free (time-to-first-token, JSON tool_call prompt):
    #   gemma4:31b           0.80s   <- fastest
    #   gpt-oss:120b         1.62s   <- chosen: largest available, still fast
    #   gpt-oss:20b          2.17s   <- lightest quota burn
    #   nemotron-3-nano:30b  2.78s
    #   minimax-m2.5         9.29s
    #
    # NOTE: the cloud catalog has no embedding models, so embeddings stay on
    # local Ollama (see ollama_url / embedding_model above). Vision stays
    # local too — cloud vision would burn quota per frame.
    #
    # Free tier meters GPU-time, not tokens, on a 5-hour session window.
    # Heavier models drain it faster.
    ollama_api_key: str = ""
    ollama_cloud_url: str = "https://ollama.com"
    ollama_cloud_model: str = "gpt-oss:120b"

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

    # ── Phase 5B: LLM provider failure resilience ──
    # 429s + 5xx + timeouts on the primary Planner/chat LLM. Retry with
    # server-directed backoff (from Retry-After / retry_after_seconds
    # headers) capped at `llm_max_retries`; on persistent failure fall
    # over to `llm_fallback_backend` if configured (empty = no fallback,
    # the caller gets a structured error). See backend/ai_modules/llm/
    # provider.py + backends/gemini_backend.py + ollama_client.py.
    llm_max_retries: int = 3
    llm_backoff_base_s: float = 2.0  # used only when server doesn't send Retry-After
    llm_fallback_backend: str = ""  # e.g. "ollama" — falls over to local on cloud failure

    # ── Phase 5A: tool execution timeouts (per-tier) ──
    # Every tool call is wrapped in asyncio.wait_for. Tier is derived from
    # the tool's source module in backend/core/tools/ (e.g. data_sources.py
    # → data_fetch tier). A tool that hangs past its budget is cancelled,
    # a structured timeout ToolResult flows up to Healer which routes to
    # RETRY-once-then-ABORT (see backend/core/healing.py). Untier'd modules
    # get tool_timeout_default_s.
    tool_timeout_default_s: float = 30.0
    tool_timeout_data_fetch_s: float = 10.0   # stock/weather/news/finance/geocode
    tool_timeout_browser_nav_s: float = 30.0  # browser_*, web_reader, page reads
    tool_timeout_llm_s: float = 60.0          # summarize/translate/llm_helper (LLM-invoking tools)

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
