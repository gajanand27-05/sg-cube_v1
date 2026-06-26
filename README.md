# SG_CUBE — Local-First AI Assistant

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-windows-lightgrey.svg)](https://www.microsoft.com/windows)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-orange.svg)](https://ollama.com/)

A voice-first, vision-aware, local-only AI assistant. Wake word triggers hands-free commands; the assistant sees your screen, remembers context, executes tools, and responds aloud — entirely offline.

---

## Architecture

```text
                    ┌──────────────────────────┐
                    │    Web Dashboard (React)  │
                    │  Tailwind / shadcn / Fz   │
                    └──────────┬───────────────┘
                               │ WebSocket + REST
                    ┌──────────▼───────────────┐
                    │   FastAPI Server (:8001)  │
                    │  Auth · Routes · WS/UI    │
                    └──────────┬───────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                 │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼──┐
     │ Wake-Word List. │ │ 3‑Tier    │ │ Agent    │
     │ (Whisper/Vosk)  │ │ Router    │ │ Pipeline │
     │ STT + TTS       │ │ Cache→    │ │ Scholar→ │
     │ (faster-whisper │ │ Rules→    │ │ Planner→ │
     │  + Piper)       │ │ LLM Agent │ │ Guardian→│
     └─────────────────┘ └───────────┘ │ Operator │
                                       │ Healer   │
                                       └──────────┘
     ┌──────────────┐  ┌────────────┐  ┌──────────┐
     │ Vision Loop  │  │ Memory     │  │ MCP      │
     │ (screen cap  │  │ ChromaDB   │  │ Server   │
     │  + VLM)      │  │ Episodic   │  │ + Client │
     └──────────────┘  │ Timeline   │  └──────────┘
                       └────────────┘
```

## Features

| Layer | Tech |
|-------|------|
| **Wake word** | Whisper (int16→float32) or Vosk, listens for "onyx" |
| **STT** | faster-whisper with silero-VAD |
| **TTS** | Piper offline neural TTS |
| **Voice pipeline** | Local (default) or LiveKit streaming (env toggle) |
| **LLM backend** | Ollama (gemma4:12b, phi3) |
| **Vision** | Periodic screen capture + Qwen2.5-VL analysis |
| **Memory** | ChromaDB (long-term, episodic) + in-memory (short-term, working, timeline, screen) |
| **Routing** | 3-tier: fuzzy cache → regex rules (~40 patterns) → LLM agent |
| **Agent pipeline** | Scholar → Planner → Guardian → Operator → Healer |
| **Tools** | 70+ built-in: system, files, weather, stocks, YouTube, email, OCR, summarization, reminders, notes, translation, games |
| **Games** | Blackjack, Hangman, Wordle, TicTacToe, Connect4, RPS |
| **MCP** | FastMCP SSE server exposes all tools; client connects to external MCP servers |
| **Observability** | Reliability metrics, tool-usage heatmap, agent state telemetry |
| **Plugins** | Auto-discovered from `backend/plugins/` |
| **Auth** | Supabase JWT (optional, local-only mode works without it) |

**Frontend:** React 19 + TypeScript 6 + Vite, Tailwind CSS + shadcn/ui + Framer Motion + Zustand. WebSocket live feed of agent state, mic levels, routing, and memory.

---

## Quick Start

### Prerequisites

- Python 3.12+
- Ollama — [download](https://ollama.com/)
- Tesseract OCR — [download](https://github.com/UB-Mannheim/tesseract/wiki) (for vision)

### Setup

```bash
# Pull models
ollama pull gemma2:2b       # Tool-calling agent
ollama pull qwen2.5-vl      # Vision model
ollama pull nomic-embed-text # Embedding model

# Python environment
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# Download offline voice models
python tools/download_vosk_model.py
python tools/download_piper_voice.py

# Configure
copy .env.example .env   # Edit if you use Supabase/LiveKit
```

### Run

```bash
# Start backend daemon (wake word + web server)
python -m backend.daemon.main

# In another terminal — start frontend dev server
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173` — the daemon serves the API on `http://127.0.0.1:8001`.

### Production

```bash
cd frontend && npm run build   # outputs to frontend/dist/
python -m backend.daemon.main  # FastAPI auto-serves the built frontend
```

---

## Environment

Copy `.env.example` to `.env`. Key settings:

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Web server bind |
| `OLLAMA_MODEL` | `phi3` | Fast intent classifier |
| `AGENT_MODEL` | `gemma4:12b` | Tool-calling agent |
| `WHISPER_MODEL` | `base` | STT model size |
| `VOICE_PIPELINE` | `local` | Switch to `livekit` for cloud pipeline |

---

## Test

```bash
python -m pytest tests/ -v
```

All phases A–G covered (35 tests).

---

## Project map

```
backend/
  daemon/          # Background services (wake word, vision, clipboard, telemetry)
  server/          # FastAPI app + routes + WebSocket
  core/            # Agent pipeline, tools, memory, router, MCP, plugins
  ai_modules/      # LLM client, STT (whisper), TTS (piper), LiveKit worker
  database/        # ChromaDB + Supabase client + migrations
frontend/          # React + Vite + Tailwind + shadcn/ui
tools/             # Dev scripts (model downloads, diagnostics, demos)
tests/             # pytest suite
```

---

## Phases

A–G all complete: tool registry → plugins → streaming ASR/TTS → LiveKit → routing → MCP → games → observability.
