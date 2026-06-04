# 🤖 SG_CUBE — Local-First AI Operating System

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-windows-lightgrey.svg)](https://www.microsoft.com/windows)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-orange.svg)](https://ollama.com/)
[![Built with Textual](https://img.shields.io/badge/built%20with-Textual-00ff41.svg)](https://textual.textualize.io/)

**SG_CUBE** is a voice-first, vision-aware, and highly integrated AI assistant designed to run entirely on your local machine. It transforms your computer into an "AI Operating System" that can see what you see, remember what you've done, and execute complex system commands via voice or text.

![SG_CUBE Terminal UI](https://via.placeholder.com/800x450.png?text=SG_CUBE+Sci-Fi+Terminal+UI+Aesthetic)

---

## 📟 The Immersive Terminal UI

SG_CUBE features a custom-built **Sci-Fi Terminal Interface** (TUI) that feels like it's pulled straight from a hacker's workstation. 

*   **🟢 Hacker Aesthetic:** A beautiful high-contrast green-on-black interface built with the **Textual** framework.
*   **📡 Live Telemetry:** Real-time visualization of mic levels, confidence scores, and multi-agent "thinking" states.
*   **⚡ Smart Routing:** Watch as the system routes your intent through Cache → Rules → LLM in real-time.
*   **👻 Pop-on-Wake:** The UI automatically minimizes when idle and "pops up" the moment you say "SG Cube", keeping your workspace clean.
*   **🛠️ Self-Healing HUD:** Monitor the "Healer" agent as it automatically recovers from tool execution errors.

---

## 🚀 Core Capabilities

### 🎙️ Voice-First Interaction
Hands-free control with local Wake-Word detection ("SG Cube"), high-accuracy STT (**faster-whisper**), and natural neural TTS (**Piper**). No data ever leaves your mic to the cloud.

### 👁️ Vision-RAG (Screen Awareness)
A dedicated vision loop that periodically captures and analyzes your screen using local VLMs (like **Qwen2.5-VL**). SG_CUBE understands what you are looking at, whether it's a code error, a chart, or a video.

### 🧠 Semantic Long-Term Memory
Powered by **ChromaDB**, the system maintains an episodic and semantic memory. It remembers facts, user preferences, and past interactions to provide deeply personalized context.

### 🤖 Multi-Agent Orchestration
A sophisticated internal architecture featuring specialized agents:
*   **Planner:** Strategizes and selects the right tools for the task.
*   **Guardian:** Verifies safety, security, and tool syntax.
*   **Operator:** Executes system commands and handles raw data.
*   **Self-Healer:** Automatically diagnoses and fixes tool failures.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **API Server** | FastAPI (Python 3.12) |
| **LLM Runtime** | Ollama (Local) |
| **STT Engine** | faster-whisper (Local) |
| **TTS Engine** | Piper (Local Neural TTS) |
| **Wake-Word** | Vosk |
| **Vector DB** | ChromaDB |
| **UI Framework** | Textual (TUI) |

---

## 📂 Project Structure

```text
D:\sg_cube_v1\
├── backend/
│   ├── ai_modules/        # STT, TTS, and LLM clients
│   ├── core/
│   │   ├── agent/         # Multi-agent logic (Planner, Guardian, etc.)
│   │   ├── memory/        # Semantic, Episodic, and Visual memory layers
│   │   ├── orchestrator/  # Intent routing and rule engine
│   │   ├── safe_executor/ # Whitelisted system command execution
│   │   └── tools/         # Native system tools (audio, files, etc.)
│   ├── daemon/            # Always-on background loop & Terminal UI
│   ├── database/          # Supabase & ChromaDB clients
│   └── server/            # FastAPI app & configuration
├── assets/                # UI assets (chimes, icons, styles)
├── tools/                 # CLI utilities for testing and setup
└── requirements.txt       # Project dependencies
```

---

## 📦 Quick Start

### 1. Prerequisites
- **Python 3.12+**
- **Ollama:** [Download Ollama](https://ollama.com/).
- **Tesseract OCR:** Required for vision features. [Download Tesseract](https://github.com/UB-Mannheim/tesseract/wiki).

### 2. Prepare Local Models
```bash
ollama pull gemma2:2b       # Default tool-calling agent
ollama pull qwen2.5-vl      # Vision model
ollama pull nomic-embed-text # Embedding model
```

### 3. Installation
```bash
# Clone and setup environment
git clone https://github.com/your-repo/sg_cube.git
cd sg_cube
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download offline models
python tools/download_vosk_model.py
python tools/download_piper_voice.py
```

---

## 🏃 Usage

### Start the AI OS
This launches the always-on background listener and the immersive Terminal UI:
```bash
python -m backend.daemon.main --ui terminal
```

### Pro Tips
- **Wake Word:** Say `"SG Cube"` followed by your command.
- **Clipboard:** SG_CUBE monitors your clipboard for context-aware actions.
- **Vision:** The system "glances" at your screen periodically to build visual context.

---

## 🧠 The Multi-Agent Cycle

SG_CUBE doesn't just call an LLM; it runs a **Scholar → Planner → Guardian → Operator → Healer** cycle:

1.  **Scholar:** Injects relevant memories (long-term facts + recent visual observations) into the context.
2.  **Planner:** Devises a multi-step strategy using system tools.
3.  **Guardian:** Verifies the plan for security and ensures parameters match the tool schema.
4.  **Operator:** Executes the tools in a safe, controlled environment.
5.  **Self-Healer:** If a tool fails, the Healer analyzes the traceback and prompts a correction.

---

## 🛠️ Troubleshooting

- **🎤 No audio detected:** Run `python tools/diagnose_mic.py` to verify your input device.
- **🐌 VLM too slow:** Ensure you have enough VRAM for `qwen2.5-vl`.
- **🔌 Ollama Connection:** Ensure the Ollama service is running and `OLLAMA_URL` is set in your `.env`.

---

<!-- Generated by SG_CUBE Documentation Tool -->
