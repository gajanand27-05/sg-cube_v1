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
    # How long local Ollama keeps a model resident after a call. Ollama's
    # default is 5 minutes, after which the next call pays a cold load —
    # measured on this machine: phi3 5260ms cold vs 107ms warm. phi3 gates
    # every deep-checked tool, so an idle gap mid-session makes the next
    # command feel broken. Sized to fit: phi3 3.8GB + nomic 323MB against a
    # 6GB card leaves ~1.8GB headroom. Local only; the cloud has no concept
    # of residency.
    ollama_keep_alive: str = "30m"
    
    # Reasoning / coding models (served by Ollama Cloud — see below)
    reasoning_model: str = "gpt-oss:120b"  # planner, complex logic
    coding_model: str = "gpt-oss:120b"     # code generation

    # General conversation
    chat_model: str = "gpt-oss:120b"       # aspirational — not currently read

    # Vision
    vision_model: str = "qwen2.5vl:3b"          # local VLM

    # STT/TTS
    whisper_model: str = "small"                # faster-whisper (legacy; see stt_manager)
    piper_voice: str = "en_US-ryan-high"        # Piper TTS voice

    # ── STT profile selection (backend/ai_modules/speech/stt_manager.py) ──
    # "auto"     — GPU + accurate model on AC, CPU + fast model on battery
    # "accurate" — always whisper_model_gpu on the GPU (pin this for a demo)
    # "fast"     — always whisper_model_cpu on the CPU
    # Save every captured utterance next to its transcript, so real
    # mis-transcriptions accumulate into a corpus instead of vanishing when
    # the turn ends. Every accuracy number so far comes from clean
    # push-to-talk audio, which is not the distribution that fails.
    #
    # OFF by default on purpose: this records everything the microphone hears
    # in a room where someone lives. Capped at 500 files by
    # capture_archive._MAX_CAPTURES.
    stt_archive_captures: bool = False

    stt_profile: str = "auto"
    # medium, not large-v3: on a 30-utterance corpus of the user's own voice
    # (tools/stt_bench.py, beam_size=1) the two were IDENTICAL — EXACT 80.0%,
    # CMD 90.0% each — while medium ran at p50 615ms vs 896ms. 281ms per
    # utterance for no measured accuracy. Caveat: that corpus is a quiet room,
    # so large-v3 may still win in noise; STT_PROFILE=accurate with
    # WHISPER_MODEL_GPU=large-v3 pins it back if a real environment shows that.
    whisper_model_gpu: str = "medium"           # AC power, cuda/float16
    whisper_model_cpu: str = "small"            # battery or no GPU, cpu/int8
    # Release the model after this many seconds idle. 0 disables. Kept well
    # above a conversational pause: unloading after every utterance would pay
    # the 2-3s load cost on the very next command.
    stt_idle_unload_s: float = 180.0

    # Warm phi3 + nomic at daemon start so the first spoken command does not
    # pay phi3's cold load (6408ms measured, vs 861ms warm).
    enable_model_preload: bool = True

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
    # How long an action that asked "should I proceed?" stays answerable.
    # Short on purpose: the pending call is also popped by the very next turn
    # whatever it says, so this only bounds the case where the user walks away
    # mid-prompt. A long window would let a "sure" aimed at something else
    # authorise an action the user has forgotten about.
    confirmation_ttl_s: float = 90.0
    # How long the mic keeps listening after the assistant ASKS something.
    # The ordinary follow-up window is 3s and starts when speech ends, which
    # is not enough to hear "should I proceed?", think, and answer — the
    # window shut before the user replied, so the answer was never even
    # transcribed. Comfortably inside confirmation_ttl_s, so the window can
    # never outlive the pending action it is waiting for.
    confirmation_followup_window_s: float = 20.0

    # The "learning layer": after every tool-using turn it fires a second LLM
    # call to extract facts and workflow patterns into long-term memory.
    #
    # Default OFF, on measurement. It is fire-and-forget, so it does not block
    # the reply — but it does not finish before the NEXT turn either, and it
    # competes with that turn for the same provider. Measured over sequential
    # tool turns: 14535ms median with it live against 6539ms with it stubbed
    # out. ~8s per turn, paid by the turn AFTER the one that triggered it.
    #
    # And it was not buying anything: the model returns patterns as objects,
    # Chroma rejects a non-string document, and every extraction was discarded
    # after the call had been paid for ("Expected document to be a str, got
    # {'workflow_name': ...}"). That coercion is fixed, so turning this on now
    # actually stores something — but its value is still unmeasured, and 8s a
    # turn is a steep price for an unmeasured feature on a voice assistant.
    enable_episodic_summarizer: bool = False

    enable_vision: bool = True      # passive screen glance every 5m
    # Perceptual-hash bits (of 256) that must differ before a glance is worth
    # a VLM run. Measured on real captures: one changed pixel scores 0, a
    # clock's worth of digits scores 1, half the screen replaced scores 57.
    # 6 sits in the empty gap between "the clock ticked" and "the user moved
    # on". Raise it to skip more aggressively on a battery-sensitive machine;
    # 0 analyses anything that is not pixel-perfect identical.
    vision_change_threshold: int = 6
    # Default OFF. The mic listener executes misheard ambient audio
    # (T-wake-word-executes-ambient-audio) and any turn it fires mutates the
    # same STM/planner state a text turn reads, which silently contaminated the
    # earlier planner measurements. Opt in with ENABLE_WAKE_WORD=true once echo
    # suppression and the follow-up content gate are both proven in the room.
    enable_wake_word: bool = False  # mic listener for the wake phrase
    # Desktop-sensitive routes (/vision, /memory, /system, /agents,
    # /diagnostics, WS /ws/ui) are loopback-only because the HUD sends no
    # credential. Turn this on if you open the HUD via this machine's LAN IP
    # instead of localhost — it widens the guard to RFC1918 peers, which means
    # anything on the same Wi-Fi can screenshot this desktop. Off by default.
    allow_lan_hud: bool = False
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
    # Loudness is not evidence of speech. Room transients measured at 2854 RMS
    # against the 800 threshold above, and were interrupting playback on their
    # own. Vosk does not decode non-speech (a click train at 3085 RMS and a
    # tone at 5656 RMS both yield an empty partial), so the debounce run must
    # also contain at least one newly decoded token. Set False to go back to
    # loudness-only — e.g. if a mic ever proves too quiet for Vosk to decode
    # the barge-in utterance at all.
    barge_in_require_speech: bool = True
    # E1 (leftovers): open-air echo test harness flag. OFF by default so
    # production barge-in keeps interrupting TTS instantly. When ON,
    # stop_speech() is deferred from wake-onset to after capture completes,
    # so the mic records the full TTS utterance instead of a ~200ms fragment
    # + silence (which Whisper hallucinates on). Only the in-flight sentence
    # keeps playing; queued sentences are still drained at wake.
    defer_stop_speech_after_capture: bool = False

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
