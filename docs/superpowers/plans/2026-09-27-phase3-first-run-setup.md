# Phase 3: first-run setup — implementation plan

Replaces "Phase 3" in `2026-09-24-laptop-release.md`. Decided 2026-09-27.

## Decisions

| Area | Decision |
|---|---|
| Keys | **One planner key required: Ollama Cloud or Gemini, either.** Groq optional. Supabase, Finnhub, OpenWeather optional. |
| No Groq key | Speech-to-text falls back to local Whisper `base` on the CPU. The spoken message names the right key (today it says "check GEMINI_API_KEY"). |
| Models | **Bundled in the installer, checksummed:** Whisper `base`, MiniLM-L6 (memory), Vosk small (wake word), the Piper voice. **Downloaded on demand**, with progress and resume: multilingual MiniLM, Whisper `small`/`medium`. |
| Browser | Installed **Edge by default**, Chrome if the user picks it. A **separate automation profile** the user signs into once. No Chromium download. |
| OCR | Open: measured below; decide before step 8. |
| Piper voice | Open: `ryan-high` (current) vs `ryan-medium`, measured below. |

## What exists today (measured 2026-09-26/27)

- Keys come only from `.env`. `paths.USER_ENV` is documented as "written by first-run setup" but nothing writes it; there is no setup route or HUD screen.
- First boot with no keys: ready in 5.7 s, no crash. Rule-engine commands work (`get_time`); anything needing the LLM fails as `LLM unavailable: ` with an empty reason and a traceback in the log.
- No Groq key: `stt_groq` raises `no_key` with no local fallback, and the spoken line names GEMINI_API_KEY.
- Only the two memory embedders are SHA-256 pinned. Whisper, Vosk and Piper are not; Vosk and Piper arrive only via manual scripts; faster-whisper calls the Hugging Face Hub on every load.
- Browser tools use Playwright's own Chromium (345 MB) with a profile in `~/sg_cube/browser_profile`; preflight tells the user to run `playwright install chromium`.

## Work, in order (one commit each, tests with each)

### 1. Planner-key requirement and honest failures
- `preflight`: new check "planner key": OK if Ollama Cloud or Gemini is registered; DOWN otherwise. Add the missing Groq check (optional: OK / DISABLED).
- `routing._cloud_or`: unchanged order (Ollama Cloud, then Gemini, then local).
- `LLM unavailable: ` → a spoken sentence that says what is missing ("no planner key is set up — open Setup in the HUD").
- Tests: no keys → the reason names the setup screen; either key alone → the planner routes to it.

### 2. Speech-to-text without Groq
- `stt_groq`: `no_key` → local Whisper `base` (the offline path it already has), not an error.
- `trigger.py` `no_key` line: name GROQ_API_KEY, and only when local Whisper is also unavailable.
- Tests: no key → local path used; message names the right key.

### 3. Setup API
- `GET /api/setup/status` → `{keys: {name: missing|saved|valid|invalid}, models: {...}, browser: {...}, ollama: {installed, running}, ocr: {...}}`.
- `POST /api/setup/keys` → validates each key with one cheap call, then writes it:
  - Ollama Cloud: `GET /api/tags` with the key; Gemini: `models.list`; Groq: `GET /openai/v1/models`.
  - Writes `USER_ENV` (`DATA_DIR/.env`): temp file + fsync + replace, keeping every other line and comment; keys never logged (RedactingFormatter already scrubs tokens; add key patterns).
  - Reloads settings in place for the keys it wrote (no restart).
- Same guard as the HUD's confirmation channel: local peer + session token.
- Tests: invalid key not written; valid key written; other `.env` lines preserved; non-local peer refused; key absent from logs.

### 4. HUD setup screen
- Shown on first run and whenever the planner key is missing; reachable from the HUD menu later.
- Fields: planner key (Ollama Cloud or Gemini, a toggle), Groq (optional), with "Test" per key and a plain line on what works without each ("Without Groq, speech-to-text runs on this PC — slower").
- Also shows: models present, browser choice (Edge/Chrome), Ollama detected or an install link.
- Frontend tests: states for missing/valid/invalid keys; the screen closes once a planner key validates.

### 5. Model manifest and bundled models
- `backend/core/models_manifest.json`: per model `{id, files: [{path, url, sha256, size}], bundled, required_for}`.
- Bundled: Whisper `base` (`model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt` from `Systran/faster-whisper-base`), MiniLM-L6 (`model.onnx`, `tokenizer.json`, already pinned), Vosk small, the Piper voice. About 360–415 MB depending on the voice.
- Load bundled Whisper from its directory (`WhisperModel(path)`), so nothing touches the Hub at runtime.
- Verify on first start (size + SHA-256), then record a verified stamp so later starts only check sizes. A mismatch: that feature reports itself unavailable with the reason, never loads a bad file.
- Tests: good files load; a flipped byte is refused with the reason; missing optional model = feature off, not a crash.

### 6. On-demand downloader
- For multilingual MiniLM and Whisper `small`/`medium`.
- Download to `<file>.part` with HTTP `Range` resume; SHA-256 check; atomic rename; retries with backoff; cancel.
- Progress over `/ws/ui` (`download_progress` event: id, bytes, total, state); the HUD shows a bar and "resume" after an interruption.
- Triggered when a setting asks for the model (e.g. `STT_PROFILE=accurate`, `MEMORY_EMBEDDER=multilingual-minilm-l12`) or from the setup screen.
- Tests (local HTTP server fixture): resume after a cut; bad checksum rejected and `.part` removed; progress events in order.

### 7. Browser: installed Edge/Chrome
- `browser_manager`: `channel = settings.browser_channel` (`"msedge"` default, `"chrome"`); profile moves to `DATA_DIR/browser_profile` (migrate the existing one on first start).
- "Sign in once" in the setup screen opens the automation browser on the sign-in page; the user signs in themselves.
- Rewrite `preflight.check_browser` to look for the installed browser, and replace the three "playwright install chromium" messages.
- Tests: channel passed through; preflight OK with the browser present, clear message without.

### 8. OCR
- Measured 2026-09-27 on 8 rendered test screenshots (4 kinds × 100%/150% scale, known text):

  | | Words right (mean) | Time per image (median) | Install size |
  |---|---|---|---|
  | Windows OCR (`Windows.Media.Ocr` via `winrt-*` packages) | 84.2% | 15 ms | 3.4 MB of Python packages; engine ships with Windows |
  | Tesseract 5.4 | 94.0% | 119 ms | 239 MB |

  Equal on dialog and article text (97–100%). Windows OCR is weaker on code (50–71% vs 86–100%: `ToolResu1t`, dropped operators) and on small status-bar text. Windows OCR languages follow the Windows language packs installed (here: en-GB). Not yet measured on real screenshots.
- Options: (a) Windows OCR by default, Tesseract optional for code-heavy reading; (b) Tesseract bundled; (c) Windows OCR only.

### 9. Ollama
- Detect installed/running (already in `local_llm_health`); the setup screen shows state and the official install link. Not bundled.

## Tests and done criteria
- A fresh Windows user account with the installer (Phase 4) reaches a working turn after entering one planner key, with no manual step.
- Suite green; new tests per step as listed.
- `preflight` shows: planner key, Groq (optional), each model verified, browser, Ollama, OCR.

## Open decisions
1. OCR engine (step 8).
2. Piper voice: `ryan-medium` is 3–6× faster to first audio (44/76/193 ms vs 138/381/1,098 ms for short/medium/long first sentences); listen before choosing. Changes the bundle by −57 MB.
3. Whether the setup screen also offers the phone link (off by default) or leaves it to `.env`.
