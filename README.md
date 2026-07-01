<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/platform-windows-lightgrey?style=for-the-badge&logo=windows&logoColor=white" />
  <img src="https://img.shields.io/badge/LLM-Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white" />
  <img src="https://img.shields.io/badge/local-Ollama-777?style=for-the-badge" />
  <img src="https://img.shields.io/badge/STT-faster--whisper-9cf?style=for-the-badge" />
  <img src="https://img.shields.io/badge/TTS-Piper-ff69b4?style=for-the-badge" />
  <img src="https://img.shields.io/badge/frontend-React-61DAFB?style=for-the-badge&logo=react&logoColor=white" />
  <img src="https://img.shields.io/badge/state-Zustand-593D88?style=for-the-badge" />
  <img src="https://img.shields.io/badge/vector-ChromaDB-9b59b6?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" />
</p>

<h1 align="center">
  ⬡ SG CUBE ⬢
</h1>

<h3 align="center">
  <i>local-first · voice-first · vision-aware</i>
</h3>

<p align="center">
  <b>Your AI assistant that sees your screen, hears your voice, remembers everything — cloud-powered agent, local privacy for voice &amp; vision.</b>
</p>

<br/>

---

<br/>

## ▸ System Architecture

```mermaid
flowchart TB
    V["🎤 Voice"] --> WW["Wake Word\nWhisper/Vosk"]
    WW --> STT["STT\nfaster-whisper"]
    STT --> ROUTER

    T["⌨️ Text"] --> UI["Web Dashboard\nReact + Tailwind"]
    UI -->|WS| API["FastAPI\n:8001"]
    UI -.->|REST| API
    API --> ROUTER

    subgraph ROUTER["🔀 3-Tier Router"]
        direction LR
        CACHE[Cache] --> RULE[Rules] -->         LLM[Gemini / Ollama]
    end

    LLM --> SCH --> PLA --> GUA --> OPR --> HLR
    HLR -.->|retry| PLA

    OPR --> TOOLS["🔧 70+ Tools\nsys · files · web · media · AI · games"]
    OPR --> MCP["🔌 MCP\nSSE + Client"]
    TOOLS --> TTS["Piper TTS"] -.-> V

    SCH -.-> MEM["💾 Memory\nChromaDB + in-memory"]
    VL["👁️ Vision Loop"] -.-> MEM
    CLIP["📋 Clipboard"] -.-> MEM
```

---

## ▸ Voice Pipeline

```mermaid
flowchart LR
    MIC[🎤 Mic] --> VAD[VAD] --> WW[Wake Word] --> STT[Whisper]
    STT --> CACHE{Match?}
    CACHE -->|miss| RULE[Rules] --> LLM[LLM]
    CACHE -->|hit| TTS
    RULE --> TTS
    LLM --> TTS
    TTS[Piper TTS] --> SP[🔊 Speaker]
```

---

## ▸ Agent Pipeline

```mermaid
flowchart TB
    REQ[Request] --> CMD[Commander] -->|inject context| PLA[Planner]
    PLA --> GUA{Guardian}
    GUA -->|unsafe| PLA
    GUA -->|safe| OPR[Operator]
    OPR -->|execute| RES{Result}
    RES -->|error| HLR[Healer] --> PLA
    RES -->|ok| DONE[Done]
```

---

## ▸ Features

| Layer | Stack | Status |
|-------|-------|--------|
| **Wake Word** | Whisper (int16→float32) / Vosk | ✅ |
| **Speech-to-Text** | faster-whisper + silero-VAD | ✅ |
| **Text-to-Speech** | Piper neural TTS | ✅ |
| **Voice Pipeline** | Local (default) or LiveKit streaming | ✅ |
| **Intent Routing** | 3-tier: Cache → Regex Rules (~40) → LLM | ✅ |
| **Agent LLM** | Gemini 2.5 Flash (cloud) / Ollama (local fallback) | ✅ |
| **Intent Classifier** | Ollama — phi3 (local, lightweight) | ✅ |
| **Vision** | Periodic screen capture + Qwen2.5-VL | ✅ |
| **Memory** | ChromaDB (long-term/episodic) + in-memory (short-term/timeline/screen) | ✅ |
| **Agent Pipeline** | Commander → Planner → Guardian → Operator → Healer | ✅ |
| **Tool System** | 70+ built-in tools (system, files, web, media, AI, games) | ✅ |
| **Games** | Blackjack · Hangman · Wordle · TicTacToe · Connect4 · RPS | ✅ |
| **MCP Protocol** | FastMCP SSE server + external MCP client | ✅ |
| **Observability** | Reliability metrics · tool-usage heatmap · agent telemetry | ✅ |
| **Plugins** | Auto-discovered from `backend/plugins/` | ✅ |
| **Auth** | Supabase JWT (optional — local mode works without it) | ✅ |
| **Frontend** | React 19 · TypeScript 6 · Vite · Tailwind · shadcn/ui · Framer Motion · Zustand | ✅ |

> WebSocket live feed of agent state, mic levels, routing decisions, and memory queries served to the dashboard in real-time.

---

## ▸ Quick Start

### Prerequisites

| Tool | Link |
|------|------|
| **Python 3.12+** | [python.org](https://python.org) |
| **Ollama** | [ollama.com](https://ollama.com) |
| **Tesseract OCR** | [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |

### Setup

```bash
# 1. Pull local models (intent classifier + embeddings + vision)
ollama pull phi3
ollama pull qwen2.5vl:3b
ollama pull nomic-embed-text

# 2. Python environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Download offline voice models
python tools/download_vosk_model.py
python tools/download_piper_voice.py

# 4. Configure
copy .env.example .env
# Set GEMINI_API_KEY in .env (get one at https://aistudio.google.com/apikey)
```

### Run

```bash
# Terminal 1 — Backend API server
python -m uvicorn backend.server.main:app --host 127.0.0.1 --port 8001

# Terminal 2 — Frontend dev server
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** — API at `http://127.0.0.1:8001`.

> **PowerShell users:** type `.\sg_cube` instead of `sg_cube`.

### Production Build

```bash
cd frontend && npm run build
python -m uvicorn backend.server.main:app --host 0.0.0.0 --port 8001   # auto-serves built frontend
```

---

## ▸ Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8001` | Web server bind address |
| `GEMINI_API_KEY` | — | Cloud LLM key (get at aistudio.google.com/apikey) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Agent model |
| `OPENROUTER_API_KEY` | — | Fallback cloud LLM key |
| `OLLAMA_MODEL` | `phi3` | Local intent classifier (lightweight) |
| `WHISPER_MODEL` | `base` | STT model size (tiny/base/small) |
| `VOICE_PIPELINE` | `local` | `local` or `livekit` |

---

## ▸ Project Map

```text
backend/
├── daemon/           # Background services
│   ├── main.py       # Entry point — starts everything
│   ├── trigger.py    # Wake word → STT → Router → Execute → TTS
│   ├── wake_word.py  # Whisper/Vosk listener
│   ├── vision_loop.py
│   ├── clipboard_watcher.py
│   └── telemetry.py
├── server/           # FastAPI application
│   ├── main.py       # App definition + route mounting
│   ├── config.py     # Pydantic-settings
│   ├── ws_ui.py      # WebSocket manager
│   └── routes/       # admin, agents, auth, execute, files,
│                      # memory, orchestrate, system, vision, voice
├── core/             # Intelligence layer
│   ├── agents/       # Commander, Planner, Guardian, Operator, Watcher
│   ├── tools/        # 70+ tools + registry + builtins (+ 6 games)
│   ├── memory/       # ChromaDB, episodic, timeline, working, screen
│   ├── orchestrator/ # Cache → Rules → LLM router
│   ├── mcp_server.py # MCP protocol (SSE + client)
│   └── plugins/      # User-plugins (auto-discovered)
├── ai_modules/       # LLM (OpenRouter client + Ollama), STT, TTS, LiveKit worker
└── database/         # ChromaDB + Supabase + migrations
frontend/
├── src/
│   ├── components/   # Dashboard, Header, Sidebar, StatusPanel
│   ├── hooks/        # useWebSocket
│   ├── stores/       # Zustand stores
│   └── pages/        # Dashboard, Chat, Vision, Memory, Agents, Files
└── package.json
tools/                # 30+ scripts (downloads, diagnostics, demos)
tests/                # pytest — 35 tests across all phases
```

---

## ▸ Test

```bash
python -m pytest tests/ -v
```

All phases A–G covered (35 tests passing).

| Phase | Feature | Status |
|-------|---------|--------|
| **A** | Tool registry bootstrap | ✅ |
| **B** | Plugin auto-discovery | ✅ |
| **C1–C2** | Streaming ASR + TTS + interrupt | ✅ |
| **C3** | LiveKit optional pipeline | ✅ |
| **D** | 3-tier routing (Cache → Rules → LLM) | ✅ |
| **E** | MCP protocol integration | ✅ |
| **F** | 6 CLI games + personality | ✅ |
| **G** | Observability + dev docs | ✅ |

---

<p align="center">
  <sub>agent model via Gemini — voice, vision &amp; memory stay local</sub>
</p>
