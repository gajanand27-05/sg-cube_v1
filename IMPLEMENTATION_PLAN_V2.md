# SG_CUBE v2 — Evolution Plan (Post-Phase 11)

This document outlines the next generation of features for SG_CUBE, transforming it from a voice assistant into a deeply integrated, screen-aware, and personalized local AI Operating System.

---

## 1. Screen-Aware Intelligence ("Eyes on the OS")
**Objective:** Enable the agent to understand and interact with the user's current visual context.

*   **Screen-RAG:**
    *   **Mechanism:** Periodic, privacy-preserving local screenshots processed via OCR (Tesseract/PaddleOCR) or a local VLM (Vision-Language Model) like `Moondream2` or `Llava-v1.6` via Ollama.
    *   **Use Case:** "What is that error message on my screen?", "Summarize the document I'm looking at," or "Find the pricing table in this browser tab."
*   **Active UI Context:**
    *   **Mechanism:** Use `pywinauto` or `accessibility APIs` to query the properties of the focused window (window title, control hierarchy).
    *   **Goal:** Provide the LLM with the exact state of the application being used.

---

## 2. Semantic Long-Term Memory (RAG)
**Objective:** Move beyond session-based memory to a persistent, searchable personal knowledge base.

*   **Local Vector Store:**
    *   **Tech:** Integrate `ChromaDB`, `LanceDB`, or `FAISS` running locally.
    *   **Process:** Every interaction, note, or "remember this" command is embedded using a local model (e.g., `all-MiniLM-L6-v2`) and stored.
*   **Episodic Recall:**
    *   **Mechanism:** When the user asks a question, the agent performs a similarity search across the vector store to retrieve relevant history.
    *   **Use Case:** "What did we decide about the project last Tuesday?", "Remember that my wife's birthday is June 12th."

---

## 3. Deep System Automation (Macros & Routines)
**Objective:** Enable complex, multi-step workflows triggered by a single command.

*   **Orchestrated Routines:**
    *   **Mechanism:** A new `RoutineEngine` that executes a sequence of tool calls with logic (if/then/loops).
    *   **Use Case:** "Start my morning" -> Check weather, read calendar, open Spotify to a specific playlist, and launch Slack.
*   **Intelligent Macros:**
    *   **Mechanism:** Record and replay UI actions. The agent can "learn" how to perform repetitive tasks in apps that lack APIs.

---

## 4. Vision Phase 2 (Physical & User Awareness)
**Objective:** Utilize the webcam for environmental and security awareness.

*   **Face-ID & Personalization:**
    *   **Mechanism:** Use `FaceNet` or `DeepFace` to recognize the user.
    *   **Goal:** Automatically load the correct user profile and "wake up" the system when the user sits down.
*   **Spatial Interaction:**
    *   **Mechanism:** Use `MediaPipe` for hand tracking or gesture control.
    *   **Use Case:** Mute the system with a "shush" gesture or skip songs with a swipe in the air.

---

## 5. Desktop Overlay & HUD (Heads-Up Display)
**Objective:** Provide non-intrusive visual feedback directly on the desktop.

*   **Sci-Fi HUD:**
    *   **Mechanism:** A transparent, "always-on-top" window (built with `PyQt` or `Tkinter` with transparency) that displays a waveform when listening.
    *   **Features:** Small unobtrusive notifications for tool results, battery status, and network health, styled in the "SG_CUBE" amber/block aesthetic.

---

## 6. Mobile Extension (Android Client)
**Objective:** Extend the local power of SG_CUBE to your pocket.

*   **Remote Mic & Speaker:** Use the phone as the primary input/output device for the PC.
*   **Seamless Handover:** "Send this map to my phone" or "Continue this summary on my desktop."
*   **Shared Clipboard:** Real-time clipboard synchronization between Android and Windows via the backend.

---

## 7. Implementation Roadmap (Draft)

1.  **Phase 12 (Memory):** Integrate ChromaDB + Embedding pipeline.
2.  **Phase 13 (Vision 1.5):** Screen-RAG basics (OCR + Ollama VLM).
3.  **Phase 14 (Automation):** Routine Engine + Macro recorder.
4.  **Phase 15 (UI):** Desktop Overlay HUD.
5.  **Phase 16 (Mobile):** Initial Android Bridge.
