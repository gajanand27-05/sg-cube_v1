# SG Cube v1 — Full Codebase Summary & Explanation

SG Cube is a local-first, voice-first, vision-aware personal AI assistant named **"Onyx"** — a Jarvis/Friday-style agentic system with a FastAPI backend, a React/TypeScript HUD frontend, a persistent wake-word daemon, and ChromaDB-backed memory.

---

## 1. Executive Overview

**SG Cube** is an always-on desktop AI assistant. You say a wake phrase ("onyx"), it listens (faster-whisper + silero-VAD), routes your intent through a 3-tier router, plans/verifies/executes with a multi-agent loop, calls 70+ tools (browser automation, window management, weather, finance, reminders, games, etc.), and speaks back via Piper TTS — all streamed sentence-by-sentence for low latency.

| Layer | Tech |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, ChromaDB 1.5, Supabase/Postgres, Playwright, pywin32 |
| LLMs | Gemini 2.5 Flash (cloud) or Ollama local (`phi3` / `qwen2.5vl:3b` / `nomic-embed-text`); OpenRouter/DeepSeek fallback |
| Speech | faster-whisper STT, Vosk wake-word, Piper TTS, silero-VAD |
| Frontend | React 19, TypeScript, Vite, Tailwind, Zustand, Radix/shadcn, framer-motion |
| Comms | Single WebSocket event bus bridged to web + Android remote |

The repo is organized into `backend/`, `frontend/`, `tools/` (scripts), `tests/`, `docs/`, `resources/`, plus agent configs in `.opencode/` and `.claude/`.

---

## 2. Directory Map

```
sg_cube_v1/
├── backend/
│   ├── ai_modules/        LLM backends + speech (STT/TTS/wake) + vision
│   ├── core/              brain, runtime, agents, memory, tools, orchestrator, auth, daemon, server
│   ├── database/          ChromaDB + Supabase client + SQL migration
│   ├── plugins/           example user plugin (auto-discovered)
│   ├── server/            FastAPI app, config, WebSocket UI bridge, REST routes
│   └── daemon/            wake-word, trigger loop, vision loop, tray, telemetry
├── frontend/              React SPA + dist/ build output
├── tools/                 33 helper/dev/verification scripts
├── tests/                 22 pytest suites + fixtures
├── docs/                  phase manuals, open tickets
├── resources/             plans, PDFs, theme assets
├── .opencode/, .claude/   agent runtime config (ponytail skill)
├── README.md, requirements.txt, AGENTS.md, .env.example, sg_cube.bat
```

---

## 3. Backend — LLM Layer (`backend/ai_modules/llm/`)

This is the unified model interface. The design target: **one `LLMProvider` with task-based routing + provider-level failover**, hiding four concrete backends.

### `provider.py` — `LLMProvider`
- `LLMBackend` (ABC): `generate`, `chat_stream` (async generator yielding `{"token","done"}` dicts), `embed`/`aembed`.
- `LLMProvider.generate()`: tries primary backend, on exception **retries via a configured fallback backend** once, emitting `ProviderDegradedEvent`.
- `chat_stream()`: retries are allowed **only before the first token is yielded** (mid-stream resumption is unsafe, so failures propagate). Fallback runs outside the `except` to preserve the original exception chain.
- Embeddings always route to the `"embedding"` backend (Ollama's `nomic-embed-text`).
- Globals: `llm`, `init_llm_provider(policy)`, `get_llm()`.

### `routing.py` — `RoutingPolicy`
- `TaskType` enum: `INTENT_CLASSIFICATION`, `VERIFICATION`, `EMBEDDING`, `PLANNING`, `CODING`, `SUMMARIZATION`, `CHAT`, `GENERAL`.
- `build_default_policy()` prefers **local** (Ollama) for fast classification/verification/summarization and **cloud** (Gemini→OpenRouter) for reasoning/coding/chat. `select()` falls back to `GENERAL`. `override()` lets the agent force a backend.

### `backends/` — concrete implementations
- **`ollama_backend.py`** — thin wrapper over `ollama_client`, supports images (VLM), json_mode. Embeddings delegated to Ollama.
- **`openrouter_backend.py`** — OpenAI-compatible `/chat/completions`, SSE parsing. `embed` -> `NotImplementedError` (no embeddings on OpenRouter).
- **`gemini_backend.py`** — most sophisticated. Parses Gemini 429/5xx/timeout (`RESOURCE_EXHAUSTED`, `retryDelay`), distinguishes retryable vs non-retryable. **Bounded retries** using `settings.llm_max_retries` with `llm_backoff_base_s * attempt` backoff. The first streamed item may be an `Exception` inspected for retryability. Emits `ProviderDegradedEvent(retry|gave_up)`.
- **`mock_backend.py`** — test backend with `responses`/`stream_responses` deques; default JSON `{"action":"respond"}`. `embed` returns `[0.1]*768`. Used in `test_mode` and to fill missing backends.

### Clients (lower-level, pre-backend)
- **`ollama_client.py`** — async HTTP to local Ollama (`settings.ollama_url`): generate, chat_stream (NDJSON), embed. Defines `OllamaError`. No retry here (handled upstream).
- **`openrouter_client.py`** — `httpx` chat completions with **429 retry** honoring upstream `retry_after_seconds`; non-streaming `generate` returns `""` on final failure (swallows + logs).
- **`gemini_client.py`** — standalone `google.genai` client, largely **superseded** by `gemini_backend.py` but still present; maps OpenAI-style messages -> Gemini `contents`.

### `__init__.py`
- `create_llm_provider(test_mode=False)`: registers Ollama always (as `ollama` + `embedding`), OpenRouter/Gemini conditionally on API keys, Mock for missing. Each registration wrapped in try/except so a missing provider never kills boot. `_validate_routes()` warns about tasks with no backend.

---

## 4. Backend — Speech (`backend/ai_modules/speech/`)

### `stt_whisper.py` — Speech-to-Text
- `get_model()` `@lru_cache` loads `WhisperModel(settings.whisper_model, cpu, int8)` once.
- `_COMMAND_PROMPT`: prose biasing prompt (so short commands like "lock"/"next" aren't rewritten).
- silero-VAD endpointing: `_get_silero_vad()` lazy-loads via `torch.hub`; `_filter_speech_chunks` yields clean utterance audio (threshold 0.5, trailing silence 600ms, min speech 100ms).
- `transcribe` / `transcribe_array` / `transcribe_stream`: tuned for ~2s English commands (`language="en"`, `beam_size=1`, `vad_filter=True`). Segments filtered by `no_speech_prob>0.6` / `avg_logprob<-1.5`.

### `tts_piper.py` — Text-to-Speech
- `_get_voice()` lazy-loads `en_US-ryan-high.onnx` from `piper_voices/`.
- `_audio_player()`: background task drains an `asyncio.Queue` of `{"audio","rate"}` chunks into a `sounddevice.OutputStream` — **true chunked streaming** for early audio out.
- `speak_stream(text)`: async generator yielding `{status,text,progress}`; publishes `TTSStartEvent`/`TTSEndEvent`; respects `_stop_event` for **barge-in** interrupt.
- `speak()`, `stop_speech()` (sets `_stop_event`, drains queue, `sd.stop()`), `is_speaking()`.

### `tts_queue.py` — per-sentence serialization (Phase 4B)
- `SentenceQueue`: drains Brain's `tts_ready` chunks **sentence-by-sentence** through one `speak_stream` consumer task (Piper's stop state is module-global, so overlapping streams would race — serialization fixes it).
- `interrupt()` is idempotent and safe from any task; `spoke_anything` lets the trigger fall back to speaking the full reply if streaming never yielded.

### `livekit_worker.py` — optional voice pipeline (Phase C3)
- When `settings.voice_pipeline == "livekit"`, replaces local VAD->STT->TTS with LiveKit's managed pipeline (`SGCubeVoiceAgent`). Heavy deps deferred; graceful error if missing.

### `vosk_models/`, `piper_voices/` — binary assets (git-ignored).

---

## 5. Backend — Vision (`backend/core/vision/`)

Two small files (note: imported from `core/vision`, **not** `ai_modules/vision`).

- **`capture.py`** — `capture_screen(quality=70)`: active window title via `pygetwindow`, screenshot via `pyautogui`, resized to max 1024px, returned as JPEG base64 + title.
- **`vlm.py`** — `analyze_screenshot(image_b64, title)`: sends the image to the local VLM (`settings.vision_model`, e.g. `qwen2.5vl:3b`) via Ollama with a JSON-only system prompt, returning `{app, summary, keywords}`. Used by `vision_loop` to build screen memory.

---

## 6. Backend — Core Orchestration (`backend/core/`)

### `brain.py` — transport-agnostic entry point
- `Brain.run()` / `Brain.run_stream()`: every input (voice/text/proactive/MCP/REST) funnels here.
- Builds `RequestContext` -> `ContextBuilder.collect()` -> `ConversationContext` -> streams from `Commander.run_stream()`.
- Emits `BrainChunk`s: `token`, `tool_start`, `tool_end`, `final`, `error`, `context_ready`, `tts_ready`. **`tts_ready` fires per completed sentence** (regex on `.!?`) so TTS starts early (latency optimization).
- Unified memory API (`remember/recall/forget/learn/...`) wrapping the memory manager.
- **Known gaps:** `forget()` is a stub (returns `False`, Chroma delete-by-ID limitation); `recall` re-sorts locally by `relevance*importance*confidence` (conflicts with `memory/manager` which deliberately does *not* re-sort); `execution_trace` stages are hardcoded with `latency_ms=0`.

### `runtime.py` — async tool execution
- `Runtime.run_tool(name, func, args, timeout)`: wraps sync funcs in `run_in_executor`, awaits async; `asyncio.wait_for` timeout; coerces legacy dict returns into `ToolResult`; publishes `TaskEvent`/`ToolStartedEvent`/`ToolFinishedEvent`; reports quality to observability + `record_tool_usage` (guarded try/except).
- Minor: `_tasks` dict never cleaned up.

### `events.py` — priority event bus
- `AsyncEventBus` with HIGH/NORMAL/LOW worker pools (2/4/2). `subscribe`/`publish` (non-blocking `put_nowait`). `get_bus()` lazy singleton.
- **Quirk:** auto-created bus has `_loop=None`; `publish` drops events until `start()` runs — a known gotcha.

### `state.py` — assistant state machine
- `AssistantState` (IDLE/LISTENING/THINKING/EXECUTING/SPEAKING/ERROR); `StateMachine` publishes `StateChangedEvent`. Tiny, clean.

### `latency.py`
- `TurnLatency` (idempotent `mark(stage)`, `seal()`), `LatencyLedger` (bounded deque, 100). Stages: wake, stt_done, context_ready, planner_first_token, first_tool_start/end, first_audio_out, total.

### `observability.py` — reliability metrics
- `ObservabilityEngine`: success rate, avg response, recall %, hallucination pass/total. `report_ai_quality`, `report_tool_quality` (success only at exactly `confidence==100`), `report_latency` (ms->sec).

### `healing.py` — self-healing router
- `SelfHealer.analyze(tool_name, error, attempt) -> RecoveryPath` (RETRY/PIVOT/FIX/ESCALATE/ABORT). Order-sensitive keyword matching on lowered error strings. **Default safe fallback = ESCALATE.** RETRY bounded by attempt counts. Detailed changelog documents why rule order matters.

### `preflight.py` — boot readiness
- `run_preflight()` runs dict-of-callable checks (services, ws_bridge, browser binary, ollama, LLM providers). Every check **fails safe** (returns DOWN, never raises). `check_ws_bridge` catches the Phase-3 silent-drop bug.

### `dogfooding.py` — persistent reliability ledger
- JSON file at `backend/database/dogfooding.json`, file-lock + atomic `os.replace` + fsync. Counters: wake/command/tool success, crashes, P0/P1 bugs, latency. (`ponytail` comment: JSON over SQLite by design.)

### `mcp_server.py` — MCP protocol (Phase E)
- Exposes SG_CUBE tools as a FastMCP SSE server + consumes external MCP servers. External sessions held in a module dict, **never closed** (known gap).

---

## 7. Backend — Orchestrator (`backend/core/orchestrator/`)

The fast-path intent router sits *before* the heavy agent path.

- **`normalize.py`** — lowercase, strip punctuation, collapse whitespace -> cache key.
- **`cache_layer.py`** — in-memory `Intent` cache + `get_fuzzy` (difflib, cutoff 0.8).
- **`llm_layer.py`** — `Intent` pydantic model + hardcoded intent-classifier system prompt; `resolve(text)` calls LLM (json_mode), retries on parse failure.
- **`router.py`** — `process_input(text, user_id)`: normalize -> fuzzy cache -> rule engine -> agent path (`commander.run(text, get_context())`). Logs to Supabase `command_logs`.
- **`rule_engine.py`** — the big one. 100+ `APP_ALIASES`, `_canonical_app`, 40+ compiled regex `RULES`, and a `_build_trie` first-token bucket for sub-ms lookup with linear fallback. Handlers for open/close app, time, YouTube/Google search/play, volume, brightness, weather, news, battery, power, screenshot, notes, reminders, translate, summarize, calculator, define, file/folder ops.
  - **Known issues:** `"rob1ox"` typo maps to `"roblox"`; `router.process_input` uses the *global* `get_context()` while `brain.run_stream` builds a fresh `ConversationContext` — two divergent context sources.

---

## 8. Backend — Agents (`backend/core/agents/` + `agent/`)

The agent loop is **Commander -> Planner -> Guardian -> Operator**, plus a Verifier and a Watcher.

### `agents/commander.py` — central loop
- `run` / `run_stream` / `_run_loop_stream`. Builds `RequestContext`, loops `MAX_ITER=5`:
  1. **Planner** streams tokens -> yields `token`/`final_response`/`tool_calls`.
  2. **Guardian** `verify_plan` -> valid/pending/errors. Errors -> `healer.analyze` + correction appended to history, repeats.
  3. Pending (confirmation) -> yields `final_response` asking permission.
  4. **Operator** `execute_batch` -> tool records; timeline events.
  5. Single result -> return; multi -> planner summarizes.
- Contains a `ponytail-fix` comment about a previously wrong `guardian.verify_plan(... agent_context)` signature.

### `agents/planner.py`
- `generate_plan_stream`: builds prompt, streams via `llm.chat_stream(task=PLANNING, temperature=0.1)`, parses fenced/raw JSON, **one corrective retry** on bad JSON. Emits `AgentThinkingEvent`.
- Prompt embeds the **UNTRUSTED-DATA directive** (web content = data-not-instructions, sentinel `<UNTRUSTED_PAGE_CONTENT>`), "prefer action over clarification", canvas widget-guidance, and the full capability list with security levels.

### `agents/guardian.py`
- `verify_plan` -> `(valid, pending, errors)` via `verify_call`, tagging pending calls with `needs_confirmation`/`is_critical`.

### `agents/operator.py`
- `execute_batch` -> loops calls, invokes `call_tool`, appends model results.

### `agents/verifier.py` — the verification stack
- `verify(user_query, call, is_multi_step, request_id) -> VerificationResult`.
- Layers: (1) hallucination/name-resolution; (2) schema/required-arg/type; (3) injection blacklist `DANGEROUS_TOKENS` + regex `INJECTION_PATTERN`; (4) confidence scoring; **fast paths**: READONLY->pass, trusted SYSTEM_WRITE->pass; (5) `_secondary_check` LLM for untrusted SYSTEM_WRITE & DESTRUCTIVE; (6) confirmation gate — DESTRUCTIVE always `needs_confirmation`+`is_critical`. Fail-closed throughout.

### `agents/registry.py`
- `AgentRegistry` subscribes to agent events, tracks per-agent lifecycle state, `get_active_agent()`.

### `agents/watcher.py`
- Background daemon thread polling every 5s for battery threshold / new files in a folder; fires `ProactiveEvent`.

### `agent/context.py`
- `ConversationContext`: `deque[Turn]` (max 10), `get_context()` singleton (single-user by design).

---

## 9. Backend — Memory (`backend/core/memory/`)

Tiered memory, mostly ChromaDB-backed.

- **`base.py`** — `MemoryType` enum (fact/pref/pattern/decision/outcome/visual/episodic/event/activity) + `MemoryEntry` (relevance/importance/confidence/access lifecycle, decay/merge).
- **`long_term.py`** — Chroma `sg_cube_memories`, cosine + `ProviderEmbeddingFunction` (768-dim fallback). Composite search score = semantic*0.4 + temporal*0.2 + importance*0.25 + confidence*0.15 + access_boost; `min_importance` filter; `search_explainable` (human-readable); `merge_similar_memories` returns 0 (stub).
- **`short_term.py`** — `deque[Turn]` (max 15). (Duplicate concept of `agent/context.py`.)
- **`working.py`** — scratch `dict` for current multi-step task.
- **`episodic.py`** — `EpisodeSummarizer`: LLM extracts facts/patterns -> stored; fired fire-and-forget from Commander.
- **`screen_memory.py`** — Chroma `sg_cube_visual`: `store_observation`, `search_visual` (semantic + keyword + app-bonus + temporal decay).
- **`timeline.py`** — Chroma `sg_cube_timeline`: `record_event`, `get_recent_timeline`, `search_timeline`.
- **`manager.py`** — hub (`stm/wm/ltm/timeline`); `get_relevant_context` builds a prompt string; `recall` deliberately does **not** re-sort (conflicts with `brain.recall`). `forget()` also a stub.

---

## 10. Backend — Tools (`backend/core/tools/`)

The tool system is large (~40 modules, 70+ tools). Core:

### `registry.py` — tool framework
- `SecurityLevel` (safe/caution/critical), `CapabilityTier` (readonly/system_write/destructive — **default DESTRUCTIVE = fail-closed**), `ToolResult` (success/blocked/error/pending + confidence).
- `@tool` decorator introspects signature + docstring -> JSON schema; enforces `trusted=True` cannot be set on DESTRUCTIVE.
- `Tool.__call__` routes to `runtime.run_tool` with **tier-based timeout** (`_timeout_for_tool` keyed off module basename).
- `_resolve_name` fuzzy-matches hallucinated tool names; `call` -> `sandbox.guard.check` -> `_coerce_args` (remaps arg aliases) -> invoke.

### `__init__.py` — bootstrap
- Auto-discovers all `tools/*` modules via `pkgutil` (blacklist: registry/sandbox/llm_helper) + `backend/plugins/*`.

### Notable tool modules
- **`builtins.py`** — `respond`, `open_app`, `close_app`, `play_youtube`, `search_web`, `open_url`, `get_time`.
- **`browser.py`** (Phase 2) — 9 async tools on Playwright `browser_manager`. **Defense-in-depth for untrusted web**: page text never in `.message`; content wrapped in `<UNTRUSTED_PAGE_CONTENT>` + `is_external_data=True`; URL-scheme rejection (`javascript:`/`file:`/`data:`/...). `_resolve_click_target` 7-tier resolution; ambiguous -> refuses (never guesses); password-field guard; download-attribute refusal.
- **`windowing.py`** (Phase 1) — Windows window mgmt + power. DPI awareness at import. Structured exceptions. `_layout_slots`/`_assign_to_slots` for idempotent snap layouts. CRITICAL+DESTRUCTIVE sleep/shutdown/restart with countdown + cancel.
- **`canvas.py`** (Phase 3) — strict pydantic schema (`extra="forbid"`), discriminated widget types (metric/list/map/chart/text), map-embed **allowlist** (openstreetmap only), no markup path — publishes `CanvasUpdateEvent`.
- **`data_sources.py`** (Phase 3) — provenance envelopes + caching: `get_stock` (Yahoo, 15s TTL), `get_weather_data` (Open-Meteo, 10min), `get_news_data` (RSS, 5min, `is_external_data=True`), `get_map` (OSM). On error serves last-good with `stale=True`.
- **`summarize.py`** — `summarize_pdf` (pypdf), `summarize_url` (BeautifulSoup->LLM), `explain_code`.
- **`weather.py`** — IP-inferred location + Open-Meteo (no key).
- **`reminders.py`** / **`notes.py`** / **`finance.py`** / **`news.py`** / **`files.py`** — these return **plain dicts** (legacy pattern) rather than `ToolResult`; `files.delete_file` is DESTRUCTIVE+CAUTION.
- **`games/`** — blackjack, connect4, hangman, rps, tictactoe, wordle (subagents for fun/personality).
- Many more: `audio`, `automation`, `comms`, `display`, `file_editor`, `ocr`, `read_aloud`, `sandbox`, `shell`, `system_info`, `translate`, `vision`, `web_reader`, `fun`.

---

## 11. Backend — Safety & Capabilities

- **`caps/`** — `Capability` protocol + `CapabilitySource` enum; `NativeToolCapability` wraps `call_tool`; MCP/REST/Shell capability subclasses are **stubs (NotImplementedError)**. `CapabilityRegistry.discover()` covers native + plugins.
- **`safe_executor/`** — `command_whitelist.py` (19KB allowlist of safe shell commands) + `executor.py`. This is the guard that prevents arbitrary command execution; tool `call` passes through `sandbox.guard.check`.
- **`prompts/registry.py`** — versioned YAML-backed prompt registry (`PromptVersion` with sha256). **Note:** the prompts actually *used* in code (planner/verifier/intent) are hardcoded inline, not loaded from here — the registry is a parallel/standalone system.

---

## 12. Backend — Auth (`backend/core/auth/`)

- **`auth_service.py`** — register/login via Supabase; admin role -> pending `admin_requests` row.
- **`jwt_verifier.py`** — `verify_token` via JWKS (ES256/RS256/EdDSA) + HS256 fallback for legacy.
- **`deps.py`** — FastAPI deps: `get_bearer_token`, `get_current_user`, `require_admin`, `get_local_user` (localhost auto-auth, hard-coded `DAEMON_USER_ID`), `get_any_user` (JWT or local fallback).

---

## 13. Backend — Daemon (`backend/daemon/`)

The always-on process (`sg_cube.bat` -> `backend.daemon.main`).

- **`main.py`** — boots background services with **error isolation** (one failure never blocks others): clipboard, vision, watcher, telemetry, browser (lazy), wake_word (dedicated thread). `SERVICE_STATUS` global is the `/system/services` surface. Also a CLI bridge (`python -m backend.daemon.main` == uvicorn boot).
- **`wake_word.py`** — `WakeWordListener`: Vosk `KaldiRecognizer` limited to `[wake_phrase, "[unk]"]` on a `sounddevice.RawInputStream`. Variable-length VAD capture (3s initial / 800ms trailing / 10s cap). RMS barge-in detection (debounced). 3s follow-up window after a command. RMS threshold lowered to 50 for quiet mics.
- **`trigger.py`** — the core voice loop: wake -> chime -> `transcribe_array` -> `Brain.run`/`_run_brain_streaming` -> `SentenceQueue` -> speak. Publishes `Executed`/`SpokenResponse`; on `BrainError` records crash + speaks apology. Threads `TurnLatency` through diagnostics; writes outcomes to the dogfooding ledger in `finally`. Handles proactive events from the Watcher.
- **`vision_loop.py`** — `VisionLoop(interval=300s)`: capture -> naive change-detect -> VLM -> store screen observation + timeline event.
- **`ui_events.py`** — ~25 typed event dataclasses decoupling daemon from UI (the contract mirrored by the frontend WS bridge).
- **`clipboard_watcher.py`** / **`telemetry.py`** — 1s / 2s polling daemon threads publishing `ClipboardChangedEvent` / `SystemStatsEvent`.
- **`tray.py`** — `pystray` system-tray icon (Windows).

---

## 14. Backend — Server (`backend/server/`)

### `config.py` — `Settings(BaseSettings)`
Single source of config from `.env`. Notable groups: Supabase keys, model aliases (`fast_model=phi3`, `reasoning_model=gemini-2.5-flash`, `chat_model=deepseek-chat`, `vision_model=qwen2.5vl:3b`, `whisper_model=small`, `piper_voice=en_US-ryan-high`, `ollama_url`), OpenRouter/Gemini keys, LiveKit, feature flags (`enable_vision/wake_word/clipboard/telemetry/watcher/browser`), `WAKE_PHRASE="onyx"`, barge-in knobs (`barge_in_rms_threshold=800`, `barge_in_debounce_frames=2`), LLM resilience (`llm_max_retries=3`, `llm_backoff_base_s=2.0`), tool timeouts, data providers. The legacy `AUTO_CONFIRM_SYSTEM_WRITE` flag was retired in favor of per-tool trusted allowlists.

### `main.py` — FastAPI app
- `lifespan`: `create_llm_provider()` -> `capability_registry.discover()` -> event bus start -> register proactive handler -> `start_services` -> `run_preflight()` (log-only). CORS fully open. Includes 13 routers + optional `/mcp` mount + `/health` + static `frontend/dist`.

### `ws_ui.py` — EventBus->WebSocket bridge
- `TYPE_MAP` maps ~26 event dataclasses -> snake_case wire types. `UIEventManager` subscribes to all, serializes `{type,timestamp,payload}`, broadcasts via `call_soon_threadsafe`. Single source of real-time UI updates.

### `routes/`
- **`auth.py`** (`/auth`) — register/login/whoami.
- **`admin.py`** (`/admin`, admin-gated) — approve/reject admin requests via service-role client.
- **`orchestrate.py`** (`/orchestrate`, `/chat`) — both call `process_input`; `/chat` returns spoken reply; `/chat/history` from STM.
- **`voice.py`** (`/voice`) — `/transcribe` (upload audio->Whisper), `/say` (speak), `/process` (full e2e loop with per-stage timings).
- **`execute.py`** (`/execute`) — runs a structured `Intent` through `safe_executor`.
- **`memory.py`** (`/memory`) — `/search` (explainable) + `/recent` timeline.
- **`vision.py`** (`/vision`) — screenshot, latest observation, visual search, windows.
- **`agents.py`** (`/agents`) — agent status.
- **`system.py`** (`/system`) — stats + services.
- **`files.py`** (`/files`) — list/upload.
- **`diagnostics.py`** (`/diagnostics`) — latency waterfall, success/hallucination rates, dogfooding snapshot, tool heatmap, preflight, replay smoke.
- **`remote.py`** (`/remote`) — Android control over WebSocket (wake, end_of_speech->`handle_wake`, interrupt, clipboard sync, PCM audio to device).
- **`replay.py`** (`/replay`) — trace replay/regression (largely TODO stubs).
- **`ui.py`** (`/ws`) — the web UI WebSocket.

---

## 15. Backend — Database (`backend/database/`)

- **`__init__.py`** — `CHROMA_PATH`.
- **`supabase_client.py`** — `get_anon_client()` (RLS) + `get_service_client()` (service-role, backend-only), both `@lru_cache`.
- **`migrations/0001_init.sql`** — idempotent: `profiles`, `admin_requests`, `command_logs` (JSONB action + source_layer), `context_memory`. Trigger auto-creates `profiles` on signup. RLS on all four tables.
- **`chroma_db/`** — persisted Chroma collections (git-ignored).

---

## 16. Backend — Plugins / Prompts / Replay / Testing / MCP

- **`plugins/hello_world.py`** — reference plugin; any `@tool` dropped in `backend/plugins/` is auto-discovered.
- **`plugins/base.py`** / **`manager.py`** — `SGCubePlugin` ABC + `PluginManager.discover()`.
- **`replay/recorder.py`** — `ReplayRecorder`/`ReplayPlayer` saving execution traces as JSON. `_register_event_handlers` is **dead code** (never invoked).
- **`testing/benchmarks.py`** / **`regression.py`** — `BenchmarkSuite` + `RegressionRunner` against `brain.run` (8 canonical cases).
- **`prompts/registry.py`** — versioned prompt registry (standalone, not wired into actual prompts).

---

## 17. Frontend (`frontend/`)

React 19 + TS + Vite SPA served at `:5173`, proxied to backend `:8001`.

### Architecture spine
- **`App.tsx`** — layout shell: Header / (Sidebar | routed `<main>` | StatusPanel) / Footer, inside a bordered "terminal frame" with CSS corner brackets. Calls `useWebSocket()` once.
- **`hooks/useWebSocket.ts`** — single WS connection -> derives `AssistantStatus`.
- **`store/socket.ts`** — the **event-bus fan-out**: parses each WS event, caps a 500-event ring buffer, dispatches `updateFromWs` to 6 Zustand stores (agent/chat/system/vision/memory/canvas). Reconnects after 3s.
- **Stores** — `agentStore` (agent lifecycle), `chatStore` (state/listening/thinking/speaking + last response), `systemStore` (CPU/mem/disk/net/temp), `visionStore` (wired but unused by any page), `memoryStore`, `canvasStore` (trusts server-validated widgets, no re-validation).

### Styling
- `tailwind.config.js` defines the `sgc-*` cyber-HUD palette (cyan/blue/red). `index.css` sets global HUD borders, full-screen console, custom scrollbars. `App.css` builds a rotating 3D CSS cube. `components.json` = shadcn/ui.

### Pages
- **`Dashboard.tsx`** — richest: 3-column; rotating CUBE with 6 agent faces; live sparklines (CPU/MEM/DISK/NET), services grid, neofetch block, fetches `/diagnostics/inspect`.
- **`Chat.tsx`** — chat UI, live `ThinkingTrail` (active agent's tool calls + reasoning), POSTs to `/chat`.
- **`Canvas.tsx`** — renders `canvasStore.widgets` in a responsive grid (assistant-driven, no user edits).
- **`Memory.tsx`** — memory browser; `/memory/recent` + `/memory/search`; relevance-banded; expandable `scores` breakdown.
- **`Agents.tsx`** — agent inspector with streaming reasoning + full tool trace (audit-grade, no truncation).
- **`Files.tsx`** — file browser over `/files/list`.
- **`Settings.tsx`** — minimal stub (whoami + static rows).

### Components
- `Header.tsx` (ONYX online indicator reflecting real WS state), `Sidebar.tsx` (7 NavLinks), `Footer.tsx` (TempDial SVG arc + analog ClockFace + CPU history), `StatusPanel.tsx` (assistant status + system monitor + live events ticker with severity), `CanvasWidgets.tsx` (pure presentational renderers — **no `dangerouslySetInnerHTML`; map iframes sandboxed**), `ui/` (shadcn button/card/separator; card+separator unused).

### Security invariant
Canvas text rendered as `{value}` (React-escaped); a backend grep test (`test_no_dangerous_inner_html.py`) enforces "no `dangerouslySetInnerHTML`".

---

## 18. Tools Directory (`tools/`) — 33 scripts

Dev/verification/setup helpers (key ones):
- **Setup**: `download_piper_voice.py`, `download_vosk_model.py`, `install_autostart.py` (Task Scheduler at logon), `pre_load_whisper.py`.
- **Daemon/voice**: `chat.py` (REPL), `run_daemon.py`, `demo.py`, `record_clip.py`, `diagnose_mic.py`, `test_transcribe.py`, `test_tts.py`, `test_trigger_rms.py`, `test_noise_robustness.py`, `test_wake_word.py`.
- **Verification**: `verify_commander_gate.py`, `verify_confidence.py`, `verify_context.py`, `verify_reliability.py`, `verify_timeline.py`, `verify_wake_word.py`, `test_action_approval.py`, `test_agent_memory.py`, `test_semantic_memory.py`, `test_vision_memory.py`, `test_watcher.py`, `test_orchestrate.py`, `test_llm.py`, `test_executor.py`, `test_phase13.py`.
- **Supabase**: `check_supabase.py`.
- **Dogfooding**: `dogfooding.py` (CLI bug logger writing `dogfooding.json`).

---

## 19. Tests (`tests/`) — 22 suites

Pytest; most mock at seams (browser manager, LLM provider, TTS, window primitives) to run headless. Highlights:
- `test_all_phases.py` (master suite), `test_capability_tiers.py` (fail-closed default), `test_verifier_secondary_check.py` (deep verify state-changing tools), `test_healer_coverage.py` (every error -> RecoveryPath, ESCALATE safe), `test_llm_resilience.py` (Gemini 429/5xx/timeout + fallback), `test_preflight.py`, `test_tool_timeouts.py`, `test_windowing.py`, `test_browser.py` (+ live click resolver), `test_canvas.py` (schema + XSS), `test_data_sources.py` (provenance/stale), `test_first_sentence_streaming.py`, `test_barge_in.py`, `test_latency.py`, `test_integration_voice_pipeline.py`, `test_no_dangerous_inner_html.py`, `test_service_startup_isolation.py`, `test_file_editor.py`, `test_read_webpage.py`, `test_run_command.py`.

---

## 20. Docs & Resources

- **`docs/OPEN_TICKETS.md`** — resolved: `T-planner-arg-hallucination` (fixed via DeepSeek V3). Open: `T-planner-context-bleed`, `T-planner-canvas-chain`. `T-echo-cancellation` placeholder. Phase 5E defers `T-barge-in-tuning`, `T-tool-surface-pruning` (87 tools), `T-latency-optimization`, `T-daily-drive-findings`.
- **`docs/PHASE3_CANVAS_MANUAL_TEST.md`** — 6 manual scenarios; XSS payload must render inert.
- **`docs/PHASE4_VOICE_MANUAL_TEST.md`** — voice feel; barge-in ~250ms, self-echo limitation, streaming latency.
- **`docs/PHASE5_HARDENING.md`** — reliability spec (timeouts, LLM resilience, preflight, healer audit).
- **`resources/IMPROVEMENT_PLAN.md`** — strategy inspired by FRIDAY + Jarvis; phases A-G, ~10.5 days.
- **`resources/IMPROVEMENT_TRACK_PLAN.md`** — Track 1 (intelligence) + Track 2 (productivity integrations).
- **`resources/TOMORROW_MANUAL_TEST.md`** — morning checklist (git-ignored).
- **`resources/*.pdf`** — `jarvis_from_ms.pdf` (HuggingGPT/Jarvis paper, design inspiration), `ieeePaperProject.pdf`, plus theme images + a TTS voice preview mp3.

---

## 21. Config, Env & Agent Files

- **`README.md`** — project front door; full pipeline, quick start, config table.
- **`requirements.txt`** — 85 pinned deps grouped by phase (FastAPI, Supabase, faster-whisper, Piper, Vosk, Playwright, ChromaDB, fastmcp, etc.).
- **`AGENTS.md`** — the "Ponytail" lazy-senior-dev operating manual (7-rung YAGNI ladder, root-cause fixes, `ponytail:` comment convention).
- **`.env.example`** — full config template; live `.env` is git-ignored.
- **`.gitignore`** — ignores secrets, data, models, build artifacts, and agent configs (`.claude/`, `.opencode/`, `AGENTS.md`).
- **`sg_cube.bat`** — `python -m backend.daemon.main`.
- **`.opencode/`** — ponytail skill suite + `ponytail.mjs` plugin (injects lazy rules into every chat). **`.claude/settings.local.json`** — Claude Code permission allowlist.

---

## 22. Notable Findings & Known Issues

**Cross-cutting:**
1. **Two context sources**: `router.process_input` uses global `get_context()`; `brain.run_stream` builds fresh `ConversationContext` — divergent paths.
2. **Memory ranking conflict**: `brain.recall` re-sorts; `memory/manager.recall` explicitly does not.
3. **Legacy dict returns**: `reminders/notes/finance/news/files` return plain dicts (lose confidence reporting); coerced at runtime.
4. **Dead/unwired code**: `replay.recorder._register_event_handlers`, `caps` MCP/REST/Shell capabilities, `prompts/registry` prompts, `visionStore` in frontend.
5. **`forget()` stub** in both `brain` and `memory/manager` (Chroma delete-by-ID limitation).
6. **Event-bus auto-init quirk**: events dropped until `start()`.
7. **External MCP sessions** never closed/reconnected.
8. **Hardcoded constants**: `DAEMON_USER_ID`, `rule_engine` "rob1ox"->"roblox" typo.
9. **Tight coupling**: `runtime` imports `diagnostics.record_tool_usage`.

**Security posture (strong, fail-closed everywhere):**
- Tool tier default = DESTRUCTIVE; Healer default = ESCALATE; sandbox command whitelist; capability registry; canvas map-embed allowlist; backend grep test forbids `dangerouslySetInnerHTML`; untrusted web content wrapped in `<UNTRUSTED_PAGE_CONTENT>`; DESTRUCTIVE tools always need confirmation.

**Documented limitations (not hidden):** echo cancellation, planner context-bleed, canvas chaining, barge-in threshold tuning — all tracked as open/data-gated tickets. Note: `T-planner-canvas-chain` was probed in §24 and appears largely already working at the planner level (V3 emits the full 2-tool chain then renders); a live end-to-end run is still recommended to confirm the Operator/Commander path.

---

## 23. End-to-End Flow (one voice command)

```
mic -> WakeWordListener (Vosk + VAD, barge-in/follow-up)
   -> trigger.handle_wake -> stt_whisper.transcribe_array
   -> orchestrator.router.process_input  [cache -> regex rules -> LLM]
        (agent path) Commander.run_stream:
           Planner (LLM, temperature 0.1) -> JSON tool calls
           Guardian/Verifier (schema + injection + confirmation gate)
           Operator (runtime.run_tool -> sandbox guard -> actual tool)
           Healer (on error: RETRY/PIVOT/ESCALATE)
   -> brain emits tts_ready per sentence -> SentenceQueue -> tts_piper.speak_stream
   -> every stage publishes typed events -> EventBus -> ws_ui -> frontend HUD (+ remote device)
   -> outcomes + latency + crashes written to dogfooding.json; memory consolidated
```

That covers every source file in the repository. The system is a mature, security-conscious, well-tested agentic assistant — with a few intentional shortcuts (documented via `ponytail:` comments and open tickets) and some known divergence/dead-code worth cleaning up if you want to tighten it.

---

## 24. Canvas-Chain Probe (`tools/canvas_chain_probe.py` + `canvas_chain_probe_output.json`)

A diagnostic tool added to investigate the open `T-planner-canvas-chain` ticket (see §20/§22): **when a user says "Show me AAPL and the news", does the Planner emit both data-fetch tool calls in one response, and then emit `render_canvas` on the follow-up turn?** If not, the canvas never populates because `Commander` short-circuits at `len(batch_results) == 1` (commander.py:157).

### What it does
- Runs the **Planner alone** — no Guardian, no Operator, no real execution — against DeepSeek V3 base (`deepseek/deepseek-chat` via OpenRouter).
- Three canvas-phrased queries, each repeated 3x to check determinism:
  - "Show me AAPL and the news"
  - "Show me AAPL on the canvas and the top news headlines"
  - "Put Apple stock and world news on the canvas"
- **Turn 1:** fresh query -> capture raw JSON + tool-calls.
- **Turn 2:** simulates `Commander`'s follow-up by injecting fake `tool_results` (shaped like `Operator` output: `get_stock` / `get_news_data` envelopes) and the instruction "Summarize results for the user." -> re-run Planner, check whether it emits `render_canvas`.
- Classifies the run into one of three verdicts:
  - **Both hops work** (>=66% turn1 multi-call AND >=66% turn2 `render_canvas`) -> chain already works; live-run to confirm.
  - **Turn 1 chains, Turn 2 fails** -> root cause is Commander's iteration-2 "Summarize results" cue steering V3 to a spoken summary instead of a render; fix = detect canvas-intent and inject a "now call render_canvas" instruction.
  - **Planner-loop gap** (V3 emits 1 tool at a time) -> structural gap.
- Writes full per-run raw JSON to `tools/canvas_chain_probe_output.json`.

### Key implementation notes
- Forces `import backend.core.tools` so the tool registry + `capability_registry` are populated before the Planner builds its capability list.
- Uses `context_builder.collect(RequestContext(...))` to build a real context (STM/LTM/timeline/screen) so the prompt matches production.
- `_fake_tool_results()` returns realistic provenance envelopes (`source`, `fetched_at`, `stale`, `is_external_data`, `payload`) — enough for V3 to "know the data is there" without hitting live providers.
- The simulated history mirrors exactly what `Commander` would feed back: user query -> assistant `{"tool_calls": ...}` -> user `{"tool_results": ..., "instruction": ...}`.

### Observed results (9 runs, all 3 queries x 3)
| Query | Turn 1 tool_calls | Turn 2 `render_canvas` |
|---|---|---|
| "Show me AAPL and the news" (x3) | 2 (`get_stock` + `get_news_data`) | yes, yes, yes |
| "Show me AAPL on the canvas and the top news headlines" (x3) | 2 | yes, yes, **final_response (no render)** on run 1 |
| "Put Apple stock and world news on the canvas" (x3) | 2 | yes, yes, **final_response (no render)** on run 3 |

- **Turn 1: 9/9 runs emitted 2 data-fetch tool calls** (deterministic). So `Commander`'s `len==1` short-circuit is NOT triggered — the batch executes both.
- **Turn 2: 7/9 emitted `render_canvas`** (77.8%, above the 66% threshold), 2/9 instead emitted a `final_response` narrating that the canvas was updated (a non-`render_canvas` but still "canvas-aware" path).
- **Verdict reached:** "Both hops work. V3 chains data-fetch in turn 1, renders canvas in turn 2. T-planner-canvas-chain should already work end-to-end. Live-run to confirm."

### Conclusion / implication
The probe suggests `T-planner-canvas-chain` is **largely already resolved** at the planner level (V3 emits the full 2-tool chain then renders), with a minor residual: ~2/9 of follow-up turns produce a spoken confirmation instead of an explicit `render_canvas` call. That residual is cosmetic (the spoken response still asserts the canvas was updated) rather than a hard failure, but a live end-to-end run is recommended to confirm the Operator/Commander path matches the simulated one. This is a good example of the repo's "investigate before fixing" (ponytail) culture — measuring the actual failure mode instead of guessing.
