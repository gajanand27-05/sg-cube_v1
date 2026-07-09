# Phase 4 Voice Feel — Manual Test Walkthrough

Follow top-to-bottom. Assume you know nothing about the phase. Servers OFF at start.

**What this tests that unit tests can't:** barge-in echo behavior with real mic/speakers, perceived time-to-first-audio in the moment, and real latency numbers per hop. Everything below requires a working mic, working speakers, and your ears.

---

## 0. Prereqs (30 seconds)

- Python venv activated at `D:\sg_cube_v1`
- Node not required for this test (the frontend can be off — Phase 4 is voice-only; only the latency curl output is text)
- **Mic + speakers must both work** — bring up Windows Sound settings and confirm your default input has a signal and your default output plays a test tone
- Wake word must be enabled: `.env` should have `ENABLE_WAKE_WORD=true` (default). Piper voice files must exist at `backend/ai_modules/speech/piper_voices/en_US-ryan-high.onnx` + `.onnx.json`
- Room quiet-ish. Not silent — but not with music or a TV going. Barge-in threshold is tuned for laptop-scale ambient, not open-office noise
- Ollama not required for these tests (STT/TTS are local, LLM path may be hit but the assertions here don't gate on LLM quality)

---

## 1. Startup

### 1a. Backend (Terminal 1)

```bash
cd D:\sg_cube_v1
python -m uvicorn backend.server.main:app --host 127.0.0.1 --port 8001
```

Confirm from a second terminal:

```bash
curl.exe http://127.0.0.1:8001/health
```

Expected: `{"status":"ok",...}`

**Also confirm the daemon services list**:

```bash
curl.exe http://127.0.0.1:8001/system/services
```

Expected: `wake_word: started` and NO error field. If it says `failed`, you likely have the wrong mic device index (`.env` → `WAKE_DEVICE=` empty for system default).

### 1b. Get ready to speak

Have this list of prompts open somewhere you can read them:

1. **"Onyx, what time is it?"** (long-response test — a stock reply the assistant knows how to speak conversationally)
2. **"Onyx, open chrome"** (short-response + tool-call test)
3. **"Onyx, tell me a two-sentence story about a robot who learns to sing."** (multi-sentence test — for first-sentence streaming)

---

## 2. Scenarios

### Scenario A — Barge-in: cut the assistant off (LOAD-BEARING)

**Steps:**
1. Say: **"Onyx, tell me a two-sentence story about a robot who learns to sing."**
2. Wait for the assistant to start speaking.
3. About 1 second into its reply, say **"stop"** or **"okay never mind"** — anything, doesn't have to be a wake word.
4. Assistant should cut off within ~250ms of you starting to speak.
5. Chime should re-play (indicating it's listening again).

**PASS looks like:**
- Assistant's speech stops mid-word or mid-sentence when you speak
- Chime plays (assistant went back to LISTENING)
- No crash, no repeated speech resumption after you stop
- **The remaining queued sentences do NOT play after you stop** (this is the queue-drain test — if sentence 2 plays after your barge-in, `SentenceQueue.interrupt()` isn't draining)

**FAIL looks like:**
- Assistant keeps talking over you (barge-in didn't trigger)
- Assistant stops but then RESUMES speaking sentence 2 (queue not drained)
- Crash / stack trace in backend log
- Chime plays multiple times in rapid succession

**Also open the backend log** while doing this. You should see a line like:

```
[wake] heard barge-in (rms=1234)
[TTS] Speech interrupted
```

If instead you see `[wake] heard wake: 'stop' ...`, that means the wake-word recognizer caught your utterance — that's fine, same outcome (TTS stopped, chime played, listening), but not the barge-in path. To test the barge-in path specifically, say something that ISN'T the wake phrase: **"never mind"**, **"stop that"**, **"actually wait"**.

### Scenario A2 — Self-echo false-fire check (the honest limitation)

**Steps:**
1. Turn your speaker volume UP (louder than you'd normally use).
2. Move your laptop so the mic is close to the speaker (about 6 inches).
3. Say: **"Onyx, what time is it?"**
4. Do NOT interrupt. Let the assistant speak the whole reply.

**PASS-in-a-quiet-room looks like:**
- Assistant speaks the full reply without cutting itself off

**FAIL (expected in some setups) looks like:**
- Assistant starts speaking, then cuts itself off after the first ~250ms because the mic heard its own voice and interpreted it as user speech

If this happens, it's the documented limitation. Two quick knobs to try:
- `.env` → `BARGE_IN_RMS_THRESHOLD=1500` (higher = harder to false-trigger)
- `.env` → `BARGE_IN_DEBOUNCE_FRAMES=3` (longer = harder to false-trigger)

If those don't work in your specific mic/speaker geometry, disable barge-in:
- `.env` → `ENABLE_BARGE_IN=false`

**Record which setup you used** — the results table has a column for it. Barge-in false-firing is an acoustic problem, not a bug — real acoustic echo cancellation is out of scope for Phase 4 (see `docs/OPEN_TICKETS.md` → T-echo-cancellation).

### Scenario B — First-sentence streaming: time-to-first-audio

**Steps:**
1. Say: **"Onyx, tell me a two-sentence story about a robot who learns to sing."**
2. Start a stopwatch (or count "one-Mississippi") the moment you STOP SPEAKING.
3. Stop the clock the moment the assistant STARTS SPEAKING.

**PASS looks like:**
- Time from "you-stopped" to "assistant-started-speaking" is noticeably shorter than before Phase 4 (roughly, a rough sentence-generation duration less than the whole-response duration)
- The assistant speaks sentence 1, then sentence 2, without an audible gap or pause between them
- **Sentence 1 starts before sentence 2 has been generated** — you can hear this if the assistant "commits" to a story arc partway through (rare)

**FAIL looks like:**
- Assistant waits for the entire reply before speaking (nothing changed from before Phase 4)
- Sentence 2 has a long silent gap after sentence 1 (the queue drain is slow)
- The reply gets spoken twice — once via streaming and once via the fallback path

**Also record the wall-clock time to first audio in the results table.** No stopwatch app? Count Mississippis, note the number.

### Scenario C — Latency breakdown from a real turn

**Steps:**
1. Clear the ledger first if you've been testing:
   ```bash
   curl.exe http://127.0.0.1:8001/diagnostics/latency
   ```
   (No clear endpoint — just note the current turn count.)
2. Say: **"Onyx, what time is it?"**
3. Wait until the assistant fully finishes speaking.
4. Immediately curl the endpoint:
   ```bash
   curl.exe http://127.0.0.1:8001/diagnostics/latency?n=1
   ```
5. Record every non-zero stage_ms in the results table.

**Expected shape:**
```json
{"turns":[{"request_id":"abc12345","mode":"voice","stages_ms":{
  "wake": 0,
  "stt_done": 850,
  "orchestrator_route": 855,
  "context_ready": 890,
  "planner_first_token": 1400,
  "first_audio_out": 2100,
  "total": 3200
}}],"count":1}
```

**PASS looks like:**
- `wake`, `stt_done`, `orchestrator_route`, `first_audio_out`, `total` all present
- `total` > `first_audio_out` > `planner_first_token` > `orchestrator_route` > `stt_done` > 0
- No stage is negative or 0 (except `wake` which is t=0 by definition)

**FAIL looks like:**
- Empty `turns` list — the turn didn't fire through the voice pipeline (mic input problem)
- Stages present but times don't make monotonic sense (e.g. `first_audio_out < planner_first_token`)
- `first_audio_out` missing — the assistant didn't speak (LLM error path taken)

**Then do it again for a tool-call turn:**
```
Say: "Onyx, open chrome"
```
Then `curl.exe http://127.0.0.1:8001/diagnostics/latency?n=1`

For that one:
- `first_tool_start` and `first_tool_end` should appear
- `first_audio_out` may or may not (depends on whether the assistant said anything conversational after the tool ran)

**This is the "SEE the slowest hop rather than guess" moment.** Look at the numbers. The hop with the largest ms delta is where a future Phase 4.5 optimization goes.

---

## 3. Results table (fill in during the test)

| # | Scenario | Expected | What I heard/saw | Pass / Fail | Notes |
|---|---|---|---|---|---|
| A | Barge-in cuts the assistant off | Speech stops within ~250ms of me speaking; chime plays; queued sentences do NOT play after |  |  |  |
| A2 | Loud-speaker echo test | Assistant does NOT interrupt itself; if it does, record the mic/speaker distance and volume |  |  | distance: __ in / vol: __ / config used: default? |
| B | Sentence 1 starts speaking before response finishes | Time-to-first-audio noticeably shorter than "wait for whole reply" |  |  | rough seconds to first audio: __ |
| B2 | Multi-sentence flows without audible gap | Sentence 1 → sentence 2 without silence between |  |  |  |
| C1 | Time-check latency breakdown | All stages present, monotonic |  |  | paste breakdown here |
| C2 | Open-chrome latency breakdown | Includes first_tool_start / first_tool_end |  |  | paste breakdown here |

---

## 4. Teardown

`Ctrl-C` the backend terminal. Confirm port is free:

```bash
netstat -ano | grep -E ":8001.*LISTENING"
```

Nothing should print. If it does, `taskkill //F //PID <pid>`.

---

## 5. Caveats — do NOT flag these as failures

- **Barge-in false-fires** in loud rooms or with speakers close to the mic. Documented limitation — real acoustic echo cancellation is out of scope for Phase 4 (see `docs/OPEN_TICKETS.md`). Kill switch: `ENABLE_BARGE_IN=false`.
- **First LLM call is slow** (Gemini cold start, or the Planner deciding tool schema on a fresh conversation). The FIRST turn after backend boot may show 3-5s `planner_first_token`. Second turn onward should be faster.
- **`/diagnostics/latency` is unauthenticated and localhost-only.** Debugging endpoint — not exposed to the network.
- **Windows `cp1252` encoding** in the backend terminal may spam `UnicodeEncodeError` on some emoji/arrow print statements. Harmless — the pipeline succeeded, the print just failed.
- **`/chat` (text-input path) is not instrumented for latency yet** — the text path uses `process_input` which doesn't create a `TurnLatency`. Extending to text is a natural follow-up.
- **Perceived time-to-first-audio is subjective** — record what you actually felt, not what you think it "should" be. If it feels the same as before Phase 4, that's a real finding worth naming.

---

## 6. If barge-in seems broken, quick triage

1. `curl.exe http://127.0.0.1:8001/system/services` — is `wake_word: started`?
2. Backend log — do you see any `[wake] listening for 'onyx'...` line at startup?
3. During TTS, does the log show `[wake] heard barge-in (rms=...)` when you speak? If no line at all appears, the RMS threshold is above your voice — try lowering `.env` → `BARGE_IN_RMS_THRESHOLD=400`.
4. If the log shows barge-in fired but the assistant keeps speaking, TTS `stop_speech()` isn't cutting through — check for stack trace in the log.
5. If sentence 2 plays AFTER barge-in interrupts sentence 1, `SentenceQueue.interrupt()` isn't draining — file that specifically (would be a real Phase 4B regression).
