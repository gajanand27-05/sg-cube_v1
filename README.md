# SG_CUBE — Local-First AI Operating System

**SG_CUBE** is a voice-first, vision-aware, and highly integrated AI assistant designed to run entirely on your local machine. It transforms your computer into an "AI Operating System" that can see what you see, remember what you've done, and execute complex system commands via voice or text.

![SG_CUBE Terminal UI](https://via.placeholder.com/800x450.png?text=SG_CUBE+Sci-Fi+Terminal+UI+Placeholder)

---

## 🚀 Key Features

*   **Voice-First Interaction:** Hands-free control with local Wake-Word detection ("SG Cube"), high-accuracy STT (**faster-whisper**), and natural neural TTS (**Piper**).
*   **Vision-RAG (Screen Awareness):** A dedicated vision loop that periodically captures and analyzes your screen using local VLMs (like **Qwen2.5-VL**), providing deep situational awareness.
*   **Semantic Long-Term Memory:** Powered by **ChromaDB**, the system remembers facts, user preferences, and past interactions to provide deeply personalized context.
*   **Multi-Agent Orchestration:** A sophisticated internal architecture featuring specialized agents:
    *   **Planner:** Strategizes and selects the right tools for the task.
    *   **Guardian:** Verifies safety, security, and tool syntax.
    *   **Operator:** Executes system commands and handles raw data.
    *   **Self-Healer:** Automatically diagnoses and fixes tool execution failures.
*   **Local-First Architecture:** Core intelligence (LLM, Vision, STT, TTS) runs offline via **Ollama**. Internet is only required for initial Supabase Auth and optional cloud-synced database features.
*   **Sci-Fi Terminal UI:** A beautiful, immersive command center built with **Textual** for the ultimate "hacker" aesthetic.
*   **Deep System Control:** Native tools for managing windows, audio, brightness, files, and even interacting with web services like YouTube.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **API Server** | FastAPI (Python 3.12) |
| **LLM Runtime** | Ollama |
| **STT Engine** | faster-whisper (Local) |
| **TTS Engine** | Piper (Local Neural TTS) |
| **Wake-Word** | Vosk |
| **Vector DB** | ChromaDB |
| **Cloud Auth/DB** | Supabase |
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

## 📦 Installation & Setup

### 1. Prerequisites
- **Python 3.12+**
- **Ollama:** [Download Ollama](https://ollama.com/).
- **Tesseract OCR:** Required for some vision features. [Download Tesseract](https://github.com/UB-Mannheim/tesseract/wiki).

### 2. Model Preparation
Pull the recommended local models via Ollama:
```bash
ollama pull gemma2:2b       # Default tool-calling agent
ollama pull qwen2.5-vl      # Vision model
ollama pull nomic-embed-text # Embedding model
```

### 3. Environment Configuration
Create a `.env` file in the root directory:
```env
SUPABASE_URL=your_project_url
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_JWT_SECRET=your_jwt_secret
OLLAMA_URL=http://localhost:11434
```

### 4. Setup Steps
1. **Clone & Venv:**
   ```bash
   git clone https://github.com/your-repo/sg_cube.git
   cd sg_cube
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. **Install:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Download Assets:**
   ```bash
   python tools/download_vosk_model.py
   python tools/download_piper_voice.py [voice-name]
   ```

---

## 🏃 Usage

### Start the SG_CUBE Daemon
This launches the always-on background listener and the immersive Terminal UI:
```bash
python -m backend.daemon.main --ui terminal
```

### Advanced Commands
- **Wake Word:** Say `"SG Cube"` followed by your command.
- **Clipboard Watcher:** Automatically monitors your clipboard for context-aware actions.
- **Vision Loop:** Automatically "glances" at your screen every 5 minutes (configurable).

---

## 🧠 The Multi-Agent Loop

SG_CUBE doesn't just call an LLM; it runs a **Scholar → Planner → Guardian → Operator → Healer** cycle:

1.  **Scholar:** Injects relevant memories (long-term facts + recent visual observations) into the context.
2.  **Planner:** Devises a multi-step strategy using system tools (e.g., "Find the file, then summarize it").
3.  **Guardian:** Verifies the plan for security and ensures parameters match the tool schema.
4.  **Operator:** Executes the tools in a safe, controlled environment.
5.  **Self-Healer:** If a tool fails (e.g., file not found), the Healer analyzes the traceback and prompts the Planner for a corrected approach.

---

## 🛠️ Troubleshooting

- **No audio detected:** Run `python tools/diagnose_mic.py` to verify your input device.
- **VLM too slow:** Ensure you have enough VRAM for `qwen2.5-vl` or use a lighter vision model.
- **Ollama Connection Refused:** Ensure the Ollama service is running and `OLLAMA_URL` is correct in `.env`.

---

<!-- Generated by SG_CUBE Documentation Tool -->
