# Phase 5 — Reliability hardening

Ships four buildable hardening layers against failure modes already
observed in this project's own history, plus one data-gated ticket set
that stays deferred until the manual tests + a day of real use produce
the data they'd need to aim correctly.

## What each part protects against

### Part A — Tool execution timeouts (`Phase 5A`)

**Protects against**: a network-crossing or subprocess-crossing tool
hanging past its budget and freezing the current voice turn. Every tool
call has always been wrapped in `asyncio.wait_for` at `runtime.py:78`,
but with a single 30s default — a stock fetch that hangs got the same
budget as a browser navigation. And a hung tool's structured error was
falling through to the Healer's generic transient block, which retried
up to 3 times — burning ~90s on a doomed call.

**How**: module-based tier assignment (a tool's source-module basename
decides its budget — `data_sources.py` → 10s, `web_reader.py`/`browser.py`
→ 30s, `summarize.py`/`translate.py`/`llm_helper.py` → 60s, everything
else → default). Healer got a new rule 3b for `"execution timed out"`
that fires BEFORE the generic transient block: RETRY-once-then-ABORT.

**Config knobs** (all seconds, .env-overridable):
```
tool_timeout_default_s      = 30.0
tool_timeout_data_fetch_s   = 10.0
tool_timeout_browser_nav_s  = 30.0
tool_timeout_llm_s          = 60.0
```

### Part B — LLM provider failure resilience (`Phase 5B`)

**Protects against**: the Gemini 429 wall this session hit repeatedly,
which blocked every voice test until the OpenRouter migration. The
OpenRouter client had server-directed 429 backoff at `openrouter_client.py:60-92`
already; Gemini backend had zero. And no fallback between providers
existed — a rate-limited primary killed the whole turn even with a
secondary registered.

**How**: Gemini backend detects `google.genai.errors.ClientError` with
429 / `ServerError` / `asyncio.TimeoutError`, parses the Gemini error
body's `retryDelay` field, sleeps for the reported delay, retries up
to `llm_max_retries`. `LLMProvider.generate` + `chat_stream` wrap the
selected backend and fall over to `settings.llm_fallback_backend` if
primary raises. Guards: skip fallback if not configured, same as
primary, or not registered. Mid-stream failures propagate unchanged
(once a token has been yielded to the caller we can't restart).

Emits `ProviderDegradedEvent` on the bus (wire type `provider_degraded`)
with `action ∈ {retry, fallback, gave_up}` so the UI can render
"Planner provider rate-limited, retrying" instead of showing a silent
hang.

**Config knobs**:
```
llm_max_retries        = 3
llm_backoff_base_s     = 2.0    (only used when server doesn't send Retry-After)
llm_fallback_backend   = ""     (e.g. "openrouter" to fall over from gemini)
```

### Part C — Startup preflight (`Phase 5C`)

**Protects against**: the dead-WS-bridge class of "silently not wired"
bug. Phase 3 shipped with `UIEventManager._setup_event_bridge()`
unreachable — every canvas / agent / spoken-response event was silently
swallowed. Caught only at manual-test time. A preflight that end-to-end
verified the bridge would have caught it at boot.

**How**: 5 checks, one registry, each fails safe (returns a `DOWN`
`PreflightCheck` with the exception text, never bubbles). Runs at
lifespan startup after `start_services()` (log-only) AND from
`GET /diagnostics/preflight` (structured JSON).

| Check | What it verifies |
|---|---|
| `services` | Reads `SERVICE_STATUS`, maps started/disabled/failed → OK/DISABLED/DOWN |
| `ws_bridge` | Forces `_setup_event_bridge()`, asserts flag flips. **Phase 3 catch.** |
| `browser` | If `ENABLE_BROWSER=true`, verifies Chromium binary via `playwright.chromium.executable_path` |
| `ollama` | 2s ping to `/api/tags`. Unreachable → DEGRADED (not DOWN — verifier + embeddings have local fallbacks) |
| `llm:{gemini,openrouter}` | Verifies each configured backend is registered. **No billable API call** — would burn quota on every boot |

**No config knobs** — preflight is passive observation, not configurable behaviour.

### Part D — Healer coverage audit (`Phase 5D`)

**Protects against**: the "unmapped error falls through to ESCALATE and
the user sees a generic please-clarify" gap. The Phase 5 recon
catalogued 20+ error-reason strings the tools now produce; audit found
8 gaps where the tool error was landing on ESCALATE instead of a
specific outcome (`Task was cancelled` → should ABORT not "ask user";
`empty symbol` → should FIX not "ask user"; `network error` → should
RETRY not "ask user"; etc.).

**How**: filled 8 specific rules (new rule 3c for cancellation, widened
rule 4 for HTTP 5xx + network errors, widened rule 4b for FIX-shape
errors, widened rule 12 for "resolved but empty" pivots). The default
ESCALATE is preserved as the explicit safe fallback — never silent,
never infinite (analyze() is stateless, retry bound lives in the
Commander). All 15 pre-Phase-5D rules regression-tested to still fire.

**No config knobs** — the routing logic is code, not configuration.

### Part E — Data-gated deferrals (`Phase 5E`)

Filed as tickets in `docs/OPEN_TICKETS.md` under a "Phase 5E —
data-gated" heading. **Explicitly not built** because they need
real-usage data:

- **T-barge-in-tuning** — RMS threshold + debounce defaults. Aim by
  running Phase 4 Scenario A2 in your actual room, not by imagining
  what a room sounds like.
- **T-tool-surface-pruning** — 87 tools; some fraction is dead weight.
  Aim by reading `/diagnostics/tools` heatmap after a week of use.
- **T-latency-optimization** — one warm sample said `planner_first_token`
  was the fat hop; a spread might say something else. Aim by reading
  `/diagnostics/latency?n=20` after a day of use.
- **T-daily-drive-findings** — placeholder for what actually breaks
  under real use. Populated by the manual tests, not by design work.

## Test count delta

Suite grew from **124** (Phase 4 finale) to **161** (Phase 5D end).
Distribution: `+8` (Part A), `+12` (Part B), `+7` (Part C), `+10` (Part D).
All prior tests still green.

## What Phase 5 does NOT touch

Deliberate scope boundaries — each traceable to an open ticket or the
"data-gated" bucket:

- Real acoustic echo cancellation (T-echo-cancellation).
- Planner prompt tickets: `T-planner-context-bleed`, `T-planner-canvas-chain`.
- Anything in Part E.
