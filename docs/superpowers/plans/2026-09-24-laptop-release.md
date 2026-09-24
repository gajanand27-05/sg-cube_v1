# Laptop release: SG-CUBE as an installable Windows app

Decided 2026-09-24:
- **Windows 10/11 only.** All 109 tools stay; no platform abstraction layer.
- **One-click installer** with a first-run wizard.
- **Floor: 8 GB RAM, no GPU.** Cloud-first by default; local models only when the
  hardware probe says they will be usable.
- **Supabase optional.** Single-user local mode needs no account.

Baseline at start: `0175c74`, 1234 backend tests passing.

## What blocks a stranger's laptop today

| Blocker | Where |
|---|---|
| All mutable state is written inside the source tree (unwritable under Program Files) | `database/`, `logs/`, `chroma_db/`, `captures/`, contacts, dogfooding, ollama restart log |
| Config only from `<repo>/.env`, hand-edited | `server/config.py` |
| Defaults tuned to the dev box (6 GB GPU, Ollama running, phi3 warm) | `config.py` defaults, `preload.py`, `llm_fallback_backend` |
| Embeddings need local Ollama; without it every memory write is refused | `memory/embedding.py` |
| `torch` pulled in only for silero-VAD (~1+ GB of install) | `speech_gate.py`, `stt_whisper.py` |
| Manual steps: venv, `playwright install chromium`, winget Tesseract, 3 model download scripts | README / tools/ |
| No launcher, no single-instance guard, no log rotation, no installer, no CI | — |

## Phase 1: relocatable runtime (foundation)
1. `backend/core/paths.py`: one module for `APP_ROOT` (read-only code/assets) and
   `DATA_DIR` (`%LOCALAPPDATA%\SG-CUBE`, override `SG_CUBE_HOME`). Dev checkout
   keeps using the repo paths when `SG_CUBE_HOME` is unset *and* the repo is
   writable, so nothing changes for the existing workflow.
2. Route every mutable path through it (list above), including model dirs
   (Vosk/Piper) so downloads land in the data dir.
3. Settings read `DATA_DIR/.env` then `APP_ROOT/.env`.
4. Rotating file log at `DATA_DIR/logs/sg_cube.log`.

## Phase 2: hardware-adaptive defaults
1. Hardware probe (RAM, CUDA, Ollama reachable + which models pulled, on AC).
2. Profile resolves unset settings: no CUDA → `stt_profile=fast`; no Ollama →
   no preload, no local fallback LLM, `enable_vision=false`, embeddings via
   Gemini; <12 GB RAM → whisper `base` on CPU.
3. Explicit `.env` values always win over the profile.
4. silero-VAD via `onnx=True` (onnxruntime already present) → drop `torch`.

## Phase 3: first-run setup
1. `/setup` API + HUD onboarding screen: API keys (Gemini required, Groq optional),
   validated with one cheap call, written to `DATA_DIR/.env`.
2. Model downloader with progress (Vosk small, Piper voice) into `DATA_DIR/models`.
3. Browser tools use the installed Edge/Chrome channel instead of downloading Chromium.
4. Tesseract optional, reported by preflight, one-click install link.

## Phase 4: launcher + installer
1. `sg_cube_launcher`: single-instance lock, free-port pick, windowless backend,
   opens the HUD, tray icon with Open / Restart / Quit / Open logs.
2. Installer (Inno Setup) bundling `uv` + lockfile: installs a private Python 3.12
   and deps into the app dir, built frontend, Start-menu + optional autostart.
   Chosen over PyInstaller: chromadb, onnxruntime, ctranslate2, vosk and piper all
   ship native libs that freeze badly; `uv` installs the same wheels the tests ran on.
3. Uninstall removes the app, keeps `DATA_DIR` unless the user ticks the box.

## Phase 5: release engineering
1. GitHub Actions on `windows-latest`: tests, frontend build, installer artifact.
2. Version from one place; `/health` reports it; installer is versioned.
3. Clean-VM smoke test checklist (8 GB, no GPU, no Ollama, no Python).
