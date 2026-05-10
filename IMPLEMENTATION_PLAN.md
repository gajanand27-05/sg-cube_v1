# SG_CUBE v1 — Voice-First MVP Implementation Plan

> Local-first AI Operating System. Voice-first build. Vision/RAG/Android deferred.
>
> **First demo target:** Say *"open notepad"* → system hears → understands → executes → speaks back.
>
> **Cloud dependency note (decided 2026-05-09):** Supabase Cloud handles auth + DB. Login + profile lookups need internet. STT (Whisper), LLM (Ollama), TTS (pyttsx3), and command execution all stay 100% local — voice loop runs offline once you're logged in.

---

## 0. Scope Lock

### In scope (Phase 1 — this plan)
- Local backend (FastAPI)
- Cloud auth + DB (Supabase Cloud — Postgres + GoTrue Auth)
- User/Admin roles + admin approval workflow (rows in `profiles` + `admin_requests`)
- Speech-to-Text (Whisper, local)
- LLM reasoning (Ollama — phi3 or llama3, local)
- 3-layer orchestrator (Cache → Rule Engine → LLM)
- SafeExecutor (whitelist of system commands)
- Text-to-Speech (pyttsx3 — offline)

### Explicitly deferred
| Module | Phase |
|---|---|
| Vision (YOLOv8, FaceNet, MobileNetV2, camera) | Phase 2 |
| RAG / embeddings / vector store | Phase 3 |
| Android client | Phase 4 |
| Multi-user concurrent sessions | Phase 4 |

**Rule:** Don't import or install dependencies for deferred phases. Stub interfaces are fine (e.g. orchestrator can have a `vision_branch()` that returns `NotImplementedError`).

---

## 1. Tech Stack (Locked)

| Layer | Choice | Why |
|---|---|---|
| API server | FastAPI | Async, fast, native Pydantic |
| DB | **Supabase Postgres (cloud)** | Managed Postgres + Auth + Row Level Security |
| Auth | **Supabase Auth (GoTrue)** → JWT (HS256) | Supabase issues JWTs; backend verifies with shared secret. Works for Android client later. |
| Password hashing | Managed by Supabase | We never see/store passwords |
| LLM runtime | Ollama | Local, simple HTTP API, model swap is trivial |
| LLM model | phi3 (start) → llama3 | phi3 is lighter for dev iteration |
| STT | Whisper (faster-whisper) | Local, accurate, GPU optional |
| TTS | **pyttsx3** | Offline, zero setup on Windows (SAPI5). Swap to Piper in Phase 1.5 if voice quality blocks demo |

---

## 2. Folder Structure

```
D:\sg_cube_v2\
├── backend/
│   ├── server/
│   │   ├── main.py                # FastAPI app entry
│   │   ├── config.py              # env + paths + JWT secret
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── voice.py           # /voice/listen, /voice/process
│   │       └── admin.py           # /admin/requests, /admin/approve
│   ├── core/
│   │   ├── auth/
│   │   │   ├── auth_service.py    # wraps Supabase signup/signin + admin-approval gate
│   │   │   ├── jwt_verifier.py    # verifies Supabase-issued JWTs (HS256, shared secret)
│   │   │   └── deps.py            # FastAPI deps: get_current_user, require_admin
│   │   ├── orchestrator/
│   │   │   ├── router.py          # the 3-layer brain
│   │   │   ├── cache_layer.py
│   │   │   ├── rule_engine.py
│   │   │   └── llm_layer.py
│   │   └── safe_executor/
│   │       ├── executor.py
│   │       └── command_whitelist.py
│   ├── ai_modules/
│   │   ├── speech/
│   │   │   ├── stt_whisper.py
│   │   │   └── tts_pyttsx3.py
│   │   └── llm/
│   │       └── ollama_client.py
│   ├── database/
│   │   ├── supabase_client.py     # anon + service-role clients
│   │   └── migrations/
│   │       └── 0001_init.sql      # tables + trigger + RLS policies
│   └── logs/
│       └── command_logs/
├── resources/
│   └── ieeePaperProject.pdf       # already present
├── tests/
│   └── (per-phase test files)
├── .env.example
├── requirements.txt
└── README.md
```

---

## 3. Database Schema (Supabase Postgres)

> `auth.users` is managed by Supabase Auth — we don't create or touch it directly.
> The tables below live in the `public` schema and FK into `auth.users`.

```sql
-- profiles: 1:1 with auth.users, holds app-specific user state
CREATE TABLE public.profiles (
    id                UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    is_approved_admin BOOLEAN NOT NULL DEFAULT FALSE,
    mode              TEXT NOT NULL DEFAULT 'personal' CHECK (mode IN ('personal','assistive')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- admin_requests: pending admin approvals
CREATE TABLE public.admin_requests (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

-- command_logs: every voice interaction
CREATE TABLE public.command_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    input_text      TEXT NOT NULL,
    resolved_action JSONB,
    source_layer    TEXT CHECK (source_layer IN ('cache','rule','llm')),
    status          TEXT CHECK (status IN ('success','blocked','error')),
    latency_ms      INTEGER,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- context_memory: basic per-user state (NOT RAG yet — Phase 3)
CREATE TABLE public.context_memory (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id TEXT,
    key        TEXT,
    value      TEXT,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger: on signup, auto-create matching profiles row
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email) VALUES (NEW.id, NEW.email);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Row Level Security
ALTER TABLE public.profiles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_requests  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.command_logs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.context_memory  ENABLE ROW LEVEL SECURITY;

-- Example policies (full set lands in 0001_init.sql during Phase 2)
CREATE POLICY "users read own profile"   ON public.profiles      FOR SELECT USING (auth.uid() = id);
CREATE POLICY "users read own commands"  ON public.command_logs  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "users read own memory"    ON public.context_memory FOR SELECT USING (auth.uid() = user_id);
-- Service-role key bypasses RLS — backend uses it for admin ops + log writes.
```

---

## 4. Phases

Each phase is **finish + verify** before moving to the next. No leapfrogging.

---

### Phase 1 — Project Skeleton & Environment ✅ COMPLETE (2026-05-09)
**Goal:** Repo runnable; FastAPI returns 200 on `/health`.

**Tasks**
1. `python -m venv .venv` — pin to Python 3.11
2. `requirements.txt` with: fastapi, uvicorn, sqlalchemy, pydantic, passlib[bcrypt], python-jose[cryptography], python-dotenv
3. Create folder structure above (empty `__init__.py` in each package)
4. `backend/server/main.py` — FastAPI app + `/health` route
5. `backend/server/config.py` — load `.env` (JWT_SECRET, DB_PATH, OLLAMA_URL)
6. `.env.example` checked in; real `.env` git-ignored

**Done when**
- `uvicorn backend.server.main:app --reload` boots cleanly
- `GET /health` → `{"status":"ok"}`

---

### Phase 2 — Supabase Setup, DB Schema & Auth
**Goal:** Working `/auth/register` and `/auth/login` backed by Supabase, with admin-approval gate.

**Tasks**

**A. Supabase project setup (manual, in browser)**
1. Create project at supabase.com (region close to user)
2. Capture from Project Settings → API:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY` (secret — never ship to client)
   - `SUPABASE_JWT_SECRET` (under JWT Settings)
3. Auth → Settings: disable email confirmation for dev (re-enable later); turn off public signups if you want closed beta

**B. Schema migration**
4. Write `backend/database/migrations/0001_init.sql` (full SQL from §3 above + complete RLS policy set)
5. Run it in Supabase SQL Editor; verify tables exist via Table Editor

**C. Backend wiring**
6. Add Phase 2 deps to `requirements.txt`:
   - `supabase` (supabase-py v2)
   - `pyjwt[crypto]` (for verifying Supabase JWTs)
7. Update `.env.example` and `.env` with the 4 Supabase vars
8. `backend/database/supabase_client.py`:
   - `get_anon_client()` — used for end-user-acting calls (respects RLS)
   - `get_service_client()` — used for admin ops + log writes (bypasses RLS)
9. `backend/core/auth/jwt_verifier.py`:
   - `verify_token(token: str) -> dict` — HS256 against `SUPABASE_JWT_SECRET`. Returns `sub` (user_id), `email`, etc.
10. `backend/core/auth/deps.py`:
    - `get_current_user` — FastAPI dep, reads `Authorization: Bearer <jwt>`, verifies, fetches `profiles` row
    - `require_admin` — dep that 403s if `role != 'admin'` or `is_approved_admin == false`
11. `backend/core/auth/auth_service.py`:
    - `register(email, password, role='user')` → calls `supabase.auth.sign_up`. If `role == 'admin'`, also insert into `admin_requests` (status='pending')
    - `login(email, password, role='user')` → calls `supabase.auth.sign_in_with_password`. Look up `profiles`. If `role == 'admin'` and `not is_approved_admin`: return `{"status":"pending"}`. Else return tokens.

**D. Routes**
12. `backend/server/routes/auth.py`:
    - `POST /auth/register` — body: email, password, role
    - `POST /auth/login` — body: email, password, role → returns access_token + refresh_token, or `pending`
    - `GET /auth/whoami` — Bearer JWT → returns profile row
13. `backend/server/routes/admin.py` (all gated by `require_admin`):
    - `GET /admin/requests` — list pending admin_requests
    - `POST /admin/approve/{user_id}` — flip `profiles.is_approved_admin = true`, mark request approved
    - `POST /admin/reject/{user_id}`
14. Wire routers into `backend/server/main.py`

**Bootstrap admin (one-time, manual)**
- Sign up the first admin via `/auth/register` (returns pending)
- In Supabase SQL editor, run: `UPDATE public.profiles SET role='admin', is_approved_admin=true WHERE email='<your_email>';`
- That admin can now approve future admin requests via `/admin/approve`

**Done when**
- ✅ Register a regular user → `auth.users` row + `profiles` row (via trigger) appear in Supabase
- ✅ Login → returns access_token (Supabase-issued JWT)
- ✅ Register with role=admin → returns `{"status":"pending"}`; row in `admin_requests`
- ✅ `/auth/whoami` with Bearer JWT returns profile
- ✅ Bootstrap admin (manually flipped) can hit `/admin/approve/{user_id}` and approve others
- ✅ Approved admin can then login with role=admin and get tokens
- ✅ Non-admin hitting `/admin/requests` → 403

---

### Phase 3 — Speech-to-Text (Whisper)
**Goal:** Audio file in → text out.

**Tasks**
1. Add `faster-whisper` to requirements
2. `ai_modules/speech/stt_whisper.py` — `transcribe(audio_path) -> str`. Load `base` model on first call, cache.
3. `routes/voice.py` — `POST /voice/transcribe` accepts multipart audio file, returns text
4. Decide mic capture path:
   - **Server-side mic** (sounddevice) — Phase 1 fastest, dev-machine-only
   - **Client uploads audio** — future-proof for Android. Pick this.
5. Add a tiny CLI helper `tools/record_clip.py` to record 5s WAV from local mic for testing

**Done when**
- Record a clip saying "open notepad" → POST to `/voice/transcribe` → response text contains "open notepad" (case-insensitive)
- Latency logged

---

### Phase 4 — LLM Layer (Ollama)
**Goal:** Text intent → structured action JSON.

**Tasks**
1. Install Ollama locally; `ollama pull phi3`
2. `ai_modules/llm/ollama_client.py` — `generate(prompt, system=None) -> str` via Ollama HTTP API (`http://localhost:11434/api/generate`)
3. Define **intent schema** (the JSON the LLM must return):
   ```json
   {"action": "open_app", "target": "notepad", "args": {}}
   ```
4. Build system prompt that constrains output to that JSON shape
5. `core/orchestrator/llm_layer.py` — wraps Ollama call, parses JSON, validates against schema (Pydantic), retries once on parse failure

**Done when**
- Calling `llm_layer.resolve("open notepad")` returns `{"action":"open_app","target":"notepad"}`
- Returns a clean error (not a crash) on malformed LLM output

---

### Phase 5 — Orchestrator (3-Layer Router)
**Goal:** Route text through Cache → Rule Engine → LLM, log which layer answered.

**Tasks**
1. `core/orchestrator/cache_layer.py` — in-memory dict + SQLite-backed persistence of (input → action) pairs. Hit = exact normalized match.
2. `core/orchestrator/rule_engine.py` — regex/keyword rules for common commands (`open <app>`, `close <app>`, `what time is it`). Returns action or `None`.
3. `core/orchestrator/router.py`:
   ```python
   def process_input(text, user):
       t0 = now()
       if hit := cache.get(text):
           return finalize(hit, "cache", t0)
       if hit := rules.match(text):
           cache.set(text, hit)
           return finalize(hit, "rule", t0)
       hit = llm_layer.resolve(text)
       cache.set(text, hit)
       return finalize(hit, "llm", t0)
   ```
4. Every call writes to `command_logs` with `source_layer` + `latency_ms`

**Done when**
- "open notepad" first call → llm layer (slow). Second call → cache (fast).
- Logs show layer + latency for each input.

---

### Phase 6 — SafeExecutor
**Goal:** Execute resolved actions safely. Block anything not whitelisted.

**Tasks**
1. `core/safe_executor/command_whitelist.py` — explicit map of `action → handler`:
   ```python
   {
     "open_app": handle_open_app,    # subprocess.Popen with allowlisted apps
     "close_app": handle_close_app,
     "get_time": handle_get_time,
   }
   ```
2. App allowlist for `open_app`: `notepad`, `calc`, `chrome`, `code` (Windows-specific paths/commands)
3. `core/safe_executor/executor.py` — `execute(action_dict, user)`:
   - Reject if action not in whitelist
   - Reject if user.mode='assistive' AND action is not in assistive-safe set (future)
   - Run handler, return result + status
4. **Block dangerous tokens** at input (`rm`, `del`, `format`, `shutdown`, `reg`, paths with `..`)

**Done when**
- `execute({"action":"open_app","target":"notepad"})` opens Notepad
- `execute({"action":"delete_system32"})` returns `{"status":"blocked"}` and logs it
- All executions land in `command_logs` with `status`

---

### Phase 7 — Text-to-Speech (pyttsx3)
**Goal:** System speaks responses back.

**Tasks**
1. Add `pyttsx3` to requirements
2. `ai_modules/speech/tts_pyttsx3.py` — `speak(text)` (sync, blocks). Lazy-init engine; pick voice + rate.
3. Wire into voice route: after execution, build a confirmation string ("Opening notepad") and `speak()` it
4. (Optional) `POST /voice/say` endpoint for direct TTS testing

**Done when**
- `speak("hello")` produces audible output on the dev machine
- After `/voice/transcribe` → execute → response is spoken

> If `pyttsx3` voice quality blocks the demo, swap to **Piper** (offline + natural) before Phase 8. Don't go to edge-tts — it breaks local-first.

---

### Phase 8 — End-to-End Voice Loop
**Goal:** The full "open notepad" demo working without manual glue.

**Tasks**
1. `routes/voice.py` → `POST /voice/process`:
   - Accept audio upload
   - STT → text
   - Orchestrator → action
   - SafeExecutor → result
   - TTS → speak confirmation
   - Return JSON: `{transcript, action, layer, latency_ms, spoken: true}`
2. Add a single CLI driver `tools/demo.py`: record 5s → POST → print result
3. Run the demo end-to-end, capture logs

**Acceptance test (the actual demo)**
| Step | Expected |
|---|---|
| Say "open notepad" | Notepad window opens |
| System speaks | "Opening notepad" |
| First run | `source_layer: llm` |
| Second run | `source_layer: cache`, latency drops sharply |
| Say "delete system32" | Notepad does NOT open. Spoken refusal. `status: blocked` in logs. |

**Phase 1 is DONE when this acceptance test passes.**

---

## 5. Per-Phase Verification Checklist

Don't move to N+1 until all of these pass for N:

- [ ] All new code has a manual test path documented
- [ ] No imports from deferred phases (no `cv2`, no `chromadb`, no `faiss`)
- [ ] `command_logs` row exists for every voice interaction
- [ ] Latency was acceptable (cache <50ms, rule <100ms, llm <3s on dev box)
- [ ] No secrets in code; `.env` only

---

## 6. Locked Decisions (2026-05-09)

| # | Decision | Choice | Reason |
|---|---|---|---|
| 1 | TTS engine | **pyttsx3** | Offline, zero-setup on Windows (uses SAPI5). Swap to Piper later if voice quality blocks demo. |
| 2 | Auth session model | **JWT (HS256) via Supabase Auth** | Supabase issues + we verify with shared secret. Works for Android client in Phase 4. |
| 3 | Mic capture | **Client-uploads-audio** | Future-proof for Android; server stays platform-agnostic. |
| 4 | DB / Auth provider | **Supabase Cloud** | Managed Postgres + GoTrue. Trade-off: login + profile lookups need internet (voice loop itself stays local). |
| 5 | Python version | **3.12.10** | 3.11 not on machine; 3.12 is compatible with all planned deps. |

---

## 7. After Phase 1 (preview, not part of this plan)

- **Phase 2 — Vision:** YOLOv8 for object detection, FaceNet for face recognition, camera ingestion module. New `ai_modules/vision/` tree. Orchestrator gets a vision branch.
- **Phase 3 — Memory + RAG:** Embedding store (likely Chroma local), retrieval into LLM context. `context_memory` table grows into a real episodic store.
- **Phase 4 — Android client:** Talks to the same FastAPI endpoints. JWT already in place pays off here.

---

## 8. Working Agreement

- Build order is **locked**. No skipping. No "I'll add vision while I'm here."
- One module at a time. Verify end-to-end before adding the next layer.
- Stub deferred-phase integration points cleanly — don't import their dependencies.
- Every voice interaction is logged. Logs are the source of truth for "is it working."
