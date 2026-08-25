# Gemini STT Consolidation — Design

**Date:** 2026-08-25
**Status:** awaiting review
**Baseline:** `855f7b1`, 1025 backend + 17 frontend tests green

## Goal

Remove Whisper. Gemini becomes the only speech-to-text path. The five agents
(Planner, Commander, Guardian, Operator, Watcher) keep their current structure
and interfaces. The frontend HUD is not touched at all.

Second, separate goal in the same effort: delete unused tool modules and orphan
dependencies. Specified in "Phase 5" below; it shares no code with the STT work
and can ship independently.

## Non-goals

- **Gemini Live API.** The camera module uses it. Considered and rejected for
  this repo: Live calls tools directly off the socket, which would bypass
  Guardian verification, the fan-out brake, the permission gate, and the rule
  engine. Revisit only as its own project.
- **Replacing Piper.** Local, fast, no quota, no network. It stays.
- **Replacing Vosk for wake-word detection.** Stays exactly as it is.
- **Any HUD change.** Explicit constraint from the owner.

## Evidence behind the decisions

Everything below was measured this session, not reasoned about. Full detail in
`decisions.md`.

**Vosk cannot serve the rule engine.** Probed both available models over the
30-clip real-voice corpus with the real `rule_engine.match`:

| | small-en-us-0.15 (68MB) | en-us-0.22-lgraph (128MB) |
|---|---|---|
| rule MATCH | 4/30 | 3/30 |
| fires WRONG rule | 1/30 | 1/30 |
| median decode | 1261ms | 4750ms |

`"stop"` decodes as `'top'` / `'the top'` on every take of both models — the one
command that most needs to be instant. `"translate good morning to hindi"` fires
translate with `lang="him the"` / `lang="in the"`, consistently, on both models.
The larger model also mishears the wake word itself (`onyx` → `'annex'`).

**Consequence, stated plainly:** with Whisper gone there is no local ASR on this
machine that can drive the rules. **Offline voice stops working.** This reverses
`debaed5`. It is a real cost, it was ruled on explicitly by the owner, and the
design's job is to make the failure honest rather than silent (see §5).

**The rule engine still survives.** It is fed by transcript text, and Gemini
produces transcript text. Rules keep running, keep their determinism, and keep
their immunity to planner hallucination — they simply need a network now.

## 1. Architecture

Only one box changes.

```
  Vosk (grammar-restricted)  ── wake word ──────────────  UNCHANGED
  wake_word.py VAD capture   ── command audio bytes ─────  UNCHANGED
┌─────────────────────────────────────────────────────┐
│  stt_gemini.transcribe_array()   ← REPLACES Whisper │  the only new code
└─────────────────────────────────────────────────────┘
  normalize.strip_wake_prefix ──────────────────────────  UNCHANGED
  rule_engine.match ── hit ⇒ execute, no planner ───────  UNCHANGED
  brain → commander → planner/guardian/operator ────────  UNCHANGED
  Piper TTS ────────────────────────────────────────────  UNCHANGED
```

**Why a drop-in and not a merged audio→plan call.** Merging transcription and
planning into one Gemini call would halve per-turn requests, which matters on a
free-tier budget. It also requires restructuring Commander and Planner, which
the owner explicitly asked to leave alone, and it would put the rule engine
downstream of a planner that had already committed to a plan. Recorded as a
Phase 6 candidate, measured before it is built, not before.

**Request cost, honestly.** Today a rule-matched command costs 0 Gemini calls.
After this change it costs 1. A planner command costs 1 today and 2 after. With
three free keys this is the binding constraint on daily use, which is why the
key pool (§2) is part of the core work and not a nicety.

## 2. `backend/ai_modules/llm/key_pool.py` — new

Ported from the camera module's `APIKeyManager`, with its two defects fixed.

Their version marks any failed key unavailable for **60 seconds**. Free-tier
limits are **per day**. So an exhausted key returns after a minute, fails again,
and after all three exhaust every turn pays three failed network calls forever.

This version classifies the failure:

| Failure | Action |
|---|---|
| 429 / `RESOURCE_EXHAUSTED` daily quota | park until next quota reset (00:00 America/Los_Angeles) |
| 429 rate-limit (per-minute) | 60s cooldown |
| 5xx, timeout, connection reset | 60s cooldown |
| 401 / 403 / malformed key | park for process lifetime, log loudly once |

Other differences from the ported original:

- Keys come from `.env` (`GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`)
  via the existing `settings` object. Not a base64 file — theirs stores keys
  `base64.b64encode`'d, which is encoding, not encryption, and reads as
  protection while providing none.
- Never writes `os.environ`. The original sets `os.environ["GEMINI_API_KEY"]`
  on every activation, mutating global process state from a library.
- No `test_connection()` port. Theirs calls `client.models.list_models()`, which
  does not exist in `google-genai` 2.10.0 (it is `.list()`), so it reports every
  valid key as invalid. **Tell the camera-module author.**

Interface:

```python
pool.acquire() -> tuple[int, str] | None     # (slot, key), honouring cooldowns
pool.report_failure(slot: int, exc: Exception) -> None
pool.report_success(slot: int) -> None
pool.status() -> list[KeyStatus]             # for logs and /diagnostics
```

`GeminiBackend` and `stt_gemini` both draw from the same pool, so a key parked
by the planner is not retried by STT one second later.

## 3. `backend/ai_modules/speech/stt_gemini.py` — new

Deliberately the **same public signature** as the Whisper module it replaces, so
`trigger.py` and `voice.py` change by one import line each and nothing
downstream knows the difference.

```python
def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict
def transcribe(audio_path: str | Path) -> dict
# -> {"text", "language", "language_probability", "duration_sec"}
```

Implementation notes:

- Encodes the array to 16kHz mono 16-bit WAV bytes and sends
  `types.Part.from_bytes(data=..., mime_type="audio/wav")`.
- **Structured output**, not a prose prompt:
  `response_schema = {"transcript": str, "speech_detected": bool}`.
  This structurally eliminates the failure Whisper's `initial_prompt` caused —
  the model reciting its own prompt as a transcript, which arrived fluent and
  confident and got dispatched as a command. `speech_detected: false` maps to
  `text: ""`, which the existing content gate already rejects. `is_prompt_echo`
  and its guard test are therefore deleted, not ported.
- Command vocabulary (app names, "Onyx") is passed as system-instruction
  context to bias recognition, the legitimate version of what the Whisper
  prompt was doing.
- Keeps the existing `latency.py` `stt_done` instrumentation so wake→first-audio
  stays measurable across the change.

## 4. Deletions

| Path | Lines | Note |
|---|---|---|
| `backend/ai_modules/speech/stt_manager.py` | 233 | whole file — profiles, CUDA PATH hack, battery policy, idle unload |
| `backend/ai_modules/speech/stt_whisper.py` | 245 | whole file — replaced by `stt_gemini.py` |
| `faster-whisper==1.1.0` | — | requirements |
| `silero-vad>=4.0.0` | — | requirements |
| nvidia cuBLAS/cuDNN wheels | — | only Whisper needed them |
| `whisper_model*`, `stt_profile`, `stt_idle_unload_s` | — | `config.py` settings |

**The silero-vad path is already dead.** `trigger.py:14` imports
`transcribe_stream`; the docstring at `trigger.py:624` claims *"Uses
`transcribe_stream` for streaming STT with partial results"*; line 655 actually
calls `transcribe_array`. `transcribe_stream` has no caller anywhere. Its ~75
lines of silero + `torch.hub` come out and the lying docstring goes with them.

**Orphan dependencies found while checking the above** — unrelated to STT, but
they are exactly the "unnecessary stuff" this effort targets:

- `ultralytics==8.4.115` is referenced by **no backend module**. Its only
  consumer in the whole repo is `tests/test_ocr_reader.py:77`, which borrows a
  sample JPEG from its site-packages assets. That is a multi-gigabyte
  dependency (it is what drags `torch` in) kept alive to supply one test image.
  Replace with a small checked-in fixture, drop the dep.
- `livekit_worker.py` (81 lines) — `requirements.txt` shows the livekit installs
  commented out. Confirm dead, then remove.

Once `ultralytics` and the silero path are gone, `torch` has no importer left in
`backend/`.

## 5. Failure behaviour — the part that must not regress

Silence is not acceptable, and neither is one generic message. The interrupt bug
committed today (`59eb62f`) was exactly this: two different situations that
sounded identical, so the user was told they were misheard when they had
interrupted. Piper is local and still works in every case below.

| Condition | Spoken response | State |
|---|---|---|
| No network | "I can't reach the network right now." | → IDLE |
| All keys quota-exhausted | "I've hit my daily limit — it resets tonight." | → IDLE |
| All keys invalid/unconfigured | "My API key isn't set up." | → IDLE |
| Gemini returned `speech_detected: false` | (silence — existing content gate) | → IDLE |

Each is a distinct branch with its own test. The state machine must reach IDLE
on every path; a turn that dies without transitioning leaves the listener stuck
in SPEAKING, which is the failure mode `59eb62f` documents.

## 6. Testing

- **Contract test:** `stt_gemini.transcribe_array` returns the same dict shape
  Whisper did, including on the empty/no-speech path.
- **Real-SDK test:** assert the methods used exist on the installed
  `google-genai` surface. Both this repo and the camera module independently
  shipped calls to the *old* SDK's method names and both stayed green because
  the tests mocked the seam. `df41d3a` added this for `generate_content`; the
  same guard covers the audio path.
- **Key pool:** quota-exhaustion parks until reset, not 60s; transient parks 60s;
  all-parked returns None rather than looping.
- **Failure branches:** one test per row of the §5 table, each asserting both
  the spoken text and the IDLE transition.
- **Rewrite, do not delete:** `test_stt_manager.py`, `test_prompt_echo_guard.py`,
  `test_lazy_init_races.py`, `test_wake_preroll.py`, `test_transcript_gate.py`,
  `test_hallucination_compound.py` and the other Whisper-touching tests are
  asserting real behaviour that still needs to hold. They get re-pointed at the
  new module, except `test_prompt_echo_guard.py`, whose bug is structurally
  impossible under structured output.
- **Live probe before "done".** Mocked-seam tests prove code on one side of a
  boundary, never delivery across it. A real capture → real Gemini call → real
  rule match must be run and its transcript recorded in `logs.md`.

## 7. Phases

1. **Key pool.** `key_pool.py` + tests; wire `GeminiBackend` to it. Ships alone.
2. **`stt_gemini.py`** + contract tests. Not yet wired.
3. **Swap.** `trigger.py` and `voice.py` imports. Full suite must stay green.
4. **Delete.** Whisper, silero, dead `transcribe_stream`, settings, deps.
5. **Failure UX** (§5) + live probe.
6. **Tool audit** — separate, independent: `core/tools/` is 6,246 lines across
   44 modules. Static reachability only; there is no per-tool usage data in
   `dogfooding.json` (only `tools_total`/`tools_success` aggregates), so this
   finds dead code, not unused-but-live code. Every removal listed for approval
   before deletion.

Phases 1-5 are the STT work. Phase 6 shares nothing with it.

## 8. Known risks

- **Latency is unmeasured.** Whisper ran on the GPU locally; Gemini adds a
  network round-trip on the critical wake→first-audio path, which is the number
  that matters. Measure at Phase 3 and report before Phase 4 deletes the
  fallback. If it regresses badly, the merged single-call design (Phase 6
  candidate) becomes the mitigation rather than an optimisation.
- **60 requests/day is a real ceiling** and this change makes every command cost
  one. Phase 1 exists so the ceiling is actually reachable.
- **No offline voice.** Accepted, ruled on, made honest in §5. Not mitigated.
