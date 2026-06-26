<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/platform-windows-lightgrey?style=for-the-badge&logo=windows&logoColor=white" />
  <img src="https://img.shields.io/badge/LLM-Ollama-orange?style=for-the-badge&logo=ollama&logoColor=white" />
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
  <b>Your AI assistant that sees your screen, hears your voice, remembers everything — and never touches the cloud.</b>
</p>

<br/>

---

<br/>

## ▸ System Architecture

```mermaid
graph TB
    subgraph User["👤 User"]
        V[🎤 Voice]
        T[⌨️ Text]
    end

    subgraph Frontend["🌐 Web Dashboard"]
        REACT[React 19 + TS 6]
        TW[Tailwind + shadcn/ui]
        ZS[Zustand Store]
        FM[Framer Motion]
        WS[WebSocket Client]
    end

    subgraph Backend["⚡ FastAPI Server :8001"]
        R[Routes / REST]
        WSE[WebSocket /ws/ui]
        AUTH[Supabase JWT]
    end

    subgraph Daemon["🧠 Daemon Services"]
        WW[Wake Word<br/>Whisper/Vosk]
        STT[faster-whisper<br/>+ silero-VAD]
        TTS[Piper TTS]
        VISION[Vision Loop<br/>screen cap + VLM]
        CB[Clipboard Watcher]
        TEL[Telemetry]
    end

    subgraph Router["🔀 3-Tier Router"]
        CACHE[Cache Layer<br/>fuzzy match]
        RULE[Rule Engine<br/>40+ patterns]
        LLM[LLM Agent<br/>gemma4:12b]
    end

    subgraph Agent["🤖 Agent Pipeline"]
        SCH[Scholar<br/>context injection]
        PLA[Planner<br/>multi-step plan]
        GUA[Guardian<br/>safety check]
        OPR[Operator<br/>tool execution]
        HLR[Healer<br/>error recovery]
    end

    subgraph Tools["🔧 Tool System"]
        SYS[System · Volume<br/>Brightness · Power]
        FILE[File Ops · Search<br/>Read · Write]
        WEB[Weather · News<br/>Stocks · Wikipedia]
        MEDIA[YouTube · Email<br/>Reminders · Notes]
        AI[OCR · Summarize<br/>Translate · Read Aloud]
        FUN[Games · Jokes<br/>Dice · Trivia]
    end

    subgraph Memory["💾 Memory Layer"]
        LT[ChromaDB<br/>Long-term]
        EP[Episodic<br/>Summaries]
        ST[Short-term]
        SCR[Screen Memory]
        TIM[Timeline]
    end

    subgraph MCP["🔌 MCP Protocol"]
        SRV[MCP SSE Server]
        CLI[MCP Client]
    end

    V --> WW
    T --> Frontend
    Frontend --> WS
    WS --> WSE
    Frontend -.-> R
    R --> AUTH
    WSE --> TEL

    WW --> STT
    STT --> Router
    R --> Router

    CACHE --> RULE --> LLM

    LLM --> SCH --> PLA --> GUA --> OPR --> HLR
    HLR -.->|retry| PLA

    OPR --> Tools
    OPR --> MCP
    SRV --> Tools
    MCP --> CLI

    SCH -.-> Memory
    VISION -.-> SCR
    CB -.-> ST

    Tools --> TTS
    TTS -.-> V
```

---

## ▸ Voice Pipeline

```mermaid
flowchart LR
    subgraph Input["🎤 Audio In"]
        direction LR
        MIC[Microphone] --> VAD[Voice Activity<br/>Detection]
    end

    subgraph Processing["⚙️ Processing"]
        direction LR
        VAD --> WW[Wake Word<br/>Whisper/Vosk]
        WW --> STT[Speech-to-Text<br/>faster-whisper]
    end

    subgraph Routing["🧭 Intent Resolution"]
        direction TB
        STT --> CACHE[(Cache<br/>fuzzy match)]
        CACHE -->|miss| RULE[Rule Engine<br/>regex patterns]
        RULE -->|fallthrough| LLM[LLM Agent<br/>gemma4:12b]
    end

    subgraph Output["🔊 Audio Out"]
        direction LR
        TTS[Piper TTS] --> SPEAKER[Speaker]
    end

    MIC --> VAD
    LLM --> TTS
    RULE --> TTS
    CACHE -->|hit| TTS

    style Input fill:#1a1a2e,stroke:#e94560,stroke-width:2px
    style Processing fill:#16213e,stroke:#0f3460,stroke-width:2px
    style Routing fill:#0f3460,stroke:#533483,stroke-width:2px
    style Output fill:#1a1a2e,stroke:#e94560,stroke-width:2px
```

---

## ▸ Agent Pipeline

```mermaid
flowchart TB
    START([Request]) --> SCH[Scholar]
    SCH -->|"injects memory + context"| PLA[Planner]

    PLA -->|"generates tool plan"| GUA{Guardian}

    GUA -->|"❌ unsafe"| PLA
    GUA -->|"✅ safe"| OPR[Operator]

    OPR -->|"execute tool"| TOOL{System Tool}
    TOOL -->|"⚠️ error"| HLR[Healer]
    TOOL -->|"✅ success"| RESP[Response]

    HLR -->|"analyzes failure"| PLA

    RESP --> DONE([Spoken + Dashboard])

    style SCH fill:#2d3436,stroke:#636e72,color:#fff
    style PLA fill:#2d3436,stroke:#0984e3,color:#fff
    style GUA fill:#2d3436,stroke:#fdcb6e,color:#fff
    style OPR fill:#2d3436,stroke:#00b894,color:#fff
    style HLR fill:#2d3436,stroke:#e17055,color:#fff
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
| **LLM Backend** | Ollama — gemma4:12b / phi3 | ✅ |
| **Vision** | Periodic screen capture + Qwen2.5-VL | ✅ |
| **Memory** | ChromaDB (long-term/episodic) + in-memory (short-term/timeline/screen) | ✅ |
| **Agent Pipeline** | Scholar → Planner → Guardian → Operator → Healer | ✅ |
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
# 1. Pull LLM models
ollama pull gemma2:2b       # tool-calling agent
ollama pull qwen2.5-vl      # vision model
ollama pull nomic-embed-text # embedding model

# 2. Python environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Download offline voice models
python tools/download_vosk_model.py
python tools/download_piper_voice.py

# 4. Configure
copy .env.example .env
```

### Run

```bash
# Terminal 1 — Backend daemon (wake word + web server)
python -m backend.daemon.main

# Terminal 2 — Frontend dev server
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** — API at `http://127.0.0.1:8001`.

### Production Build

```bash
cd frontend && npm run build
python -m backend.daemon.main   # FastAPI auto-serves built frontend
```

---

## ▸ Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Web server bind address |
| `OLLAMA_MODEL` | `phi3` | Fast intent classifier model |
| `AGENT_MODEL` | `gemma4:12b` | Tool-calling agent model |
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
│   ├── agents/       # Scholar, Planner, Guardian, Operator, Watcher
│   ├── tools/        # 70+ tools + registry + builtins (+ 6 games)
│   ├── memory/       # ChromaDB, episodic, timeline, working, screen
│   ├── orchestrator/ # Cache → Rules → LLM router
│   ├── mcp_server.py # MCP protocol (SSE + client)
│   └── plugins/      # User-plugins (auto-discovered)
├── ai_modules/       # LLM client, STT, TTS, LiveKit worker
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
  <sub>built with ⚡ — entirely offline, entirely yours</sub>
</p>
