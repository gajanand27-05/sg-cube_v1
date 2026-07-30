# SG Cube v1 — Project Plan

## Overview

SG Cube is a **local-first, voice-first, vision-aware personal AI assistant** ("Onyx"). Full-stack: FastAPI Python backend + React/TypeScript frontend. Persistent background daemon with wake-word, speech-to-text, text-to-speech, vision loop, and ChromaDB-backed memory.

---

## Architecture

### 1. Backend (`backend/`)

#### 1a. Server Layer (`backend/server/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan (boot LLM, capabilities, event bus, services, preflight), mounts 13 routers + MCP |
| `config.py` | Pydantic `Settings(BaseSettings)` — single `.env` source for all config |
| `ws_ui.py` | `UIEventManager` — bridges EventBus → WebSocket JSON for the frontend |

**Routes (`backend/server/routes/`)** — 15 route files:
- `auth.py` — register/login/whoami
- `admin.py` — admin-gated approve/reject
- `voice.py` — transcribe, say, process (e2e with per-stage timings)
- `orchestrate.py` — `/orchestrate`, `/chat`, `/chat/history`
- `execute.py` — run structured Intent through safe_executor
- `vision.py` — screenshot, observations, visual search, windows
- `memory.py` — search (explainable), recent timeline
- `agents.py` — agent status
- `system.py` — stats + services
- `files.py` — list/upload
- `diagnostics.py` — latency waterfall, heatmap, preflight, dogfooding
- `remote.py` — Android control via WebSocket
- `replay.py` — trace replay/regression (largely TODO)
- `ui.py` — web UI WebSocket
- `agents.py` — agent status

#### 1b. Intelligence Layer (`backend/ai_modules/`)
| Module | Files | Role |
|--------|-------|------|
| **LLM** | `provider.py`, `routing.py`, `backends/` | Unified `LLMProvider` with task-based routing + fallback. 4 backends: Ollama, OpenRouter, Gemini, Mock |
| **Speech** | `stt_whisper.py`, `tts_piper.py`, `tts_queue.py`, `livekit_worker.py` | faster-whisper STT, Piper neural TTS (streaming + barge-in), optional LiveKit pipeline |

#### 1c. Core Orchestration (`backend/core/`)
| File | Role |
|------|------|
| `brain.py` | Transport-agnostic entry point: builds context, runs Commander, yields `BrainChunk`s |
| `runtime.py` | Async tool executor with timeout + TaskEvent publishing |
| `events.py` | `AsyncEventBus` with HIGH/NORMAL/LOW priority worker pools |
| `state.py` | Assistant state machine (IDLE/LISTENING/THINKING/EXECUTING/SPEAKING/ERROR) |
| `latency.py` | `TurnLatency` — marks stages (wake → first_audio_out → total) |
| `observability.py` | Success rate, recall %, hallucination pass rate |
| `healing.py` | `SelfHealer.analyze()` → RETRY/PIVOT/FIX/ESCALATE/ABORT based on error keyword matching |
| `preflight.py` | Startup readiness checks (services, browser, Ollama, LLM providers) |
| `dogfooding.py` | Persistent JSON-ledger of reliability counters (file-lock + atomic write) |
| `mcp_server.py` | FastMCP SSE server + external MCP client sessions |

#### 1d. Agent Pipeline (`backend/core/agents/`)
| Agent | File | Role |
|-------|------|------|
| **Commander** | `commander.py` | Central loop: Planner → Guardian → Operator → Healer (max 5 iterations) |
| **Planner** | `planner.py` | LLM prompt → JSON tool calls, one corrective retry on bad JSON |
| **Guardian** | `guardian.py` | Routes each call through `verifier.verify()` → valid/pending/errors |
| **Operator** | `operator.py` | Executes tool batch via `call_tool()` |
| **Verifier** | `agent/verifier.py` | 6-layer safety stack: hallucination, schema, injection, confidence, secondary LLM check, confirmation gate |

#### 1e. Memory System (`backend/core/memory/`)
| Tier | Type | Backend |
|------|------|---------|
| Long-term | facts, preferences, patterns | ChromaDB (`sg_cube_memories`) |
| Episodic | auto-summarized turn insights | ChromaDB |
| Screen | visual observations | ChromaDB (`sg_cube_visual`) |
| Timeline | chronological events | ChromaDB (`sg_cube_timeline`) |
| Short-term | recent turns (deque, max 15) | In-memory |
| Working | scratch for multi-step tasks | In-memory dict |

#### 1f. Orchestrator (fast-path router)
| File | Role |
|------|------|
| `router.py` | `process_input()`: normalize → fuzzy cache → rule engine → LLM → agent path |
| `rule_engine.py` | 40+ compiled regex rules for open/close app, time, YouTube, search, volume, weather, etc. |
| `cache_layer.py` | In-memory Intent cache with difflib fuzzy (0.8 cutoff) |
| `llm_layer.py` | LLM intent classification (json_mode) |

#### 1g. Tools (`backend/core/tools/`)
~40 modules, 70+ tools. Key groups:
- **System**: windowing, display, audio, shell, system_info, automation, files, file_editor
- **Web**: browser (Playwright), web_reader, news, finance (Yahoo), weather (Open-Meteo)
- **Media**: ocr (Tesseract), vision, read_aloud, translate
- **AI**: llm_helper, summarize (PDF/URL/code), memory, data_sources
- **Games**: blackjack, connect4, hangman, rps, tictactoe, wordle
- **Misc**: builtins, reminders, notes, comms, fun, sandbox, canvas

#### 1h. Daemon (`backend/daemon/`)
| File | Role |
|------|------|
| `main.py` | Boots background services with error isolation |
| `wake_word.py` | Vosk `KaldiRecognizer` + VAD capture + barge-in + follow-up window |
| `trigger.py` | Voice loop: wake → transcribe → Brain.run → SentenceQueue → speak |
| `vision_loop.py` | Periodic screen capture → VLM → store screen memory |
| `clipboard_watcher.py` | Polls clipboard every 1s |
| `telemetry.py` | CPU/mem/disk every 2s |
| `ui_events.py` | ~25 typed event dataclasses (the UI contract) |

---

### 2. Frontend (`frontend/`)

**Stack**: React 18 + TypeScript + Vite 6 + Tailwind CSS 3 + Zustand + Three.js (3D cube)

| Layer | Files | Role |
|-------|-------|------|
| **Entry** | `main.tsx`, `App.tsx`, `index.css` | App shell with HUD layout, CSS cube |
| **Components** | `Header.tsx`, `BottomBar.tsx`, `Panel.tsx`, `AICorePanel.tsx`, `CubeVisualization.tsx`, `AppBackground.tsx`, `ErrorBoundary.tsx` | Dashboard chrome |
| **Hooks** | `useUiEvents.ts` | WebSocket connection → derives `AssistantStatus` |
| **Stores** | `/stores/socket.ts` (fan-out to 6 Zustand stores) | agent/chat/system/vision/memory/canvas |

---

### 3. Tools & Tests

| Directory | Count | Purpose |
|-----------|-------|---------|
| `tools/` | 33 scripts | Setup (download models), diagnostics, verification, demos |
| `tests/` | 22 pytest suites | Phase A-G, 35+ tests covering tools, routing, security, voice, latency, browser, canvas |

---

### 4. Docs

| File | Content |
|------|---------|
| `docs/OPEN_TICKETS.md` | 7 resolved + 5 open/data-gated tickets (context bleed, canvas chain, echo cancellation, etc.) |
| `docs/PHASE3_CANVAS_MANUAL_TEST.md` | 6 manual scenarios for canvas rendering |
| `docs/PHASE4_VOICE_MANUAL_TEST.md` | Voice feel test: barge-in, streaming latency |
| `docs/PHASE5_HARDENING.md` | Reliability spec: timeouts, LLM resilience, preflight, healer audit |
| `SG_CUBE_CODEBASE_SUMMARY.md` | Auto-generated 470-line comprehensive codebase analysis |

---

## Data Flow

```
Mic → WakeWordListener (Vosk + VAD)
  → trigger.handle_wake
    → stt_whisper.transcribe_array
      → orchestrator.router.process_input [cache → rules → LLM]
        → Commander.run_stream:
            1. Planner (LLM, temp 0.1) → JSON tool calls
            2. Guardian/Verifier (schema + injection + confirmation)
            3. Operator (runtime.run_tool → sandbox → actual tool)
            4. Healer (on error: RETRY/PIVOT/ESCALATE)
        → brain emits tts_ready per sentence
          → SentenceQueue → tts_piper.speak_stream
→ Every stage publishes events → EventBus → ws_ui → frontend HUD
→ Outcomes + latency → dogfooding.json
```

---

## Known Issues & Open Tickets

| Ticket | Status | Summary |
|--------|--------|---------|
| T-planner-arg-hallucination | **Resolved** | Gemini used wrong arg names; fixed by DeepSeek V3 migration |
| T-planner-turn-stale | **Resolved** | Commander snapshotted history before adding current turn → model answered previous question |
| T-ai-metrics-stream-path | **Resolved** | `_emit_metrics` never called from `chat_stream()` |
| T-agent-reasoning-conversational | **Resolved** | `AgentReasoningEvent` published only in tool_calls branch |
| T-rule-tier-overmatch | **Resolved** | normalize() destroyed punctuation + greedy regex catch-alls intercepted 11/15 questions |
| T-panel-listener-state-lost-on-remount | **Resolved** | useUiEventListener doesn't seed from `latest` |
| T-planner-context-bleed | Open | STM contamination changes Planner tool selection |
| T-planner-canvas-chain | Re-classified | V3 chains data-fetch but sometimes emits spoken confirmation instead of `render_canvas` |
| T-wake-word-executes-ambient-audio | **Resolved** | Echo gate at dispatch point: `_is_dispatchable` + `was_recently_spoken`; 22 tests (19 matcher + 3 e2e loopback); live probe fixed 3 bugs during development |
| T-echo-cancellation | Data-gated | Real AEC deferred |
| T-barge-in-tuning | Data-gated | Threshold/debounce need real-room data |
| T-tool-surface-pruning | Data-gated | Needs usage telemetry before pruning 87 tools |
| T-latency-optimization | Data-gated | Needs spread across 20+ turns |
| T-daily-drive-findings | Placeholder | Whatever breaks in real use |

---

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, Uvicorn, Pydantic v2 |
| LLM | Gemini 2.5 Flash / Ollama (phi3, qwen2.5vl) / OpenRouter (DeepSeek V3) |
| STT | faster-whisper + silero-VAD |
| TTS | Piper neural TTS (streaming, barge-in) |
| Wake Word | Vosk |
| Embeddings | Ollama nomic-embed-text |
| Vector DB | ChromaDB 1.5 |
| Database | Supabase (Postgres + auth) |
| Browser | Playwright (Chromium) |
| Frontend | React 18, TypeScript, Vite 6, Tailwind 3, Three.js, Zustand |
| MCP | FastMCP (SSE) |
| Platform | Windows (pywin32, pycaw, screen-brightness-control, pygetwindow, pyautogui) |
