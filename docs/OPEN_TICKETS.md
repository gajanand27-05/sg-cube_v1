# Open tickets

One-line trackers for known bugs / open threads. Longer than a line means it's not a ticket anymore, it's a document.

## T-planner-arg-hallucination — RESOLVED 2026-07-09

**Original bug**: Planner (Gemini 2.5 Flash) called `get_stock(ticker=...)` when the tool declares `symbol=`. Blocked "show me AAPL on the canvas."

**Resolution**: LLM migration to DeepSeek V3 base (`deepseek/deepseek-chat` via OpenRouter). Retest of the same prompt produced `get_stock(symbol='AAPL')` — correct arg name, real result. V3 reads tool schemas properly where Gemini fumbled.

**Regression risk**: if you roll back to Gemini for any reason, the `ticker`/`symbol` class of bug returns. The `ticker`→`symbol` alias band-aid is still available if that happens.

## T-planner-context-bleed (opened 2026-07-09)

**The bug**: STM/recent-conversation contamination changes the Planner's tool selection. Observed twice: (1) "what windows are open" triggered `get_stock_price` because the prior turn was about AAPL; (2) after several "I need clarification..." replies accumulated in STM, V3 pattern-matched and hallucinated a nonexistent rejection ("the request was flagged as potentially irrelevant to our current context").

**Not blocking**: fresh phrasing gets past it. But it's a real ergonomic bug — same user asks the same question twice, gets different tools called.

**Fix direction**: cap `context.recent_conversation` to fewer turns (currently `[-5:]`) or drop turns older than a topic switch. Prompt-engineering may also help ("prior turns are for context only — do not let them override the current request").

## T-planner-canvas-chain (opened 2026-07-09)

**The bug**: On canvas requests, the Planner picks the first natural tool (e.g. `get_stock`) but doesn't chain `render_canvas` afterward. Result: user asks to render a widget, gets a spoken text answer instead.

**Fix direction**: extend the "PREFER ACTION OVER CLARIFICATION" section of `backend/core/agents/planner.py` with explicit multi-tool chaining language for canvas requests. Small prompt tune, own commit.

## T-echo-cancellation (Phase 4 out-of-scope, may resurface)

**Placeholder** for the "real acoustic echo cancellation" thread that Phase 4's barge-in spec explicitly punts on. If the room-quiet threshold/debounce turns out to be insufficient in real use, this becomes a real ticket.

---

# Phase 5E — data-gated (DO NOT build without usage data)

These are reliability items that cannot be aimed correctly until the two manual test docs are run and the assistant has been used for real for a day. Building any of them against my imagination — instead of against what actually breaks — is the "hardening the wrong things" failure mode the Phase 5 spec explicitly warned against. Left as explicit tickets so future-me knows what's waiting and why it's waiting.

## T-barge-in-tuning (data-gated: Phase 4 Scenario A2)

**What's blocked**: the RMS threshold (default 800) and debounce (default 2 frames ≈ 250ms) in `.env` may false-fire on the assistant's own TTS bleed. Real acoustic behaviour depends on mic + speaker geometry that only your setup knows.

**What we need before touching this**: the Phase 4 manual test's Scenario A2 result. Run it, record volume/distance/false-fire rate. If the defaults false-trigger, propose either `BARGE_IN_RMS_THRESHOLD=1500` + `BARGE_IN_DEBOUNCE_FRAMES=3` (harder to fire) or `ENABLE_BARGE_IN=false` (disable in your specific room). Not model-agnostic — laptop-scale defaults will not fit an open-office setup.

**Do not**: pre-tune against synthetic mic input. Guaranteed to require a re-tune the moment you use it live.

## T-tool-surface-pruning (data-gated: real usage telemetry)

**What's blocked**: the tool registry has 87 tools (per README). Some fraction is dead weight — never invoked by real user turns — and pruning them reduces the Planner's context window pressure + shortens the capability list the model has to scan on every planning call.

**What we need before touching this**: at least a week of real usage. `/diagnostics/tools` already tracks per-tool call counts + success rate. Read the heatmap, sort by `calls`, look at the long tail. Anything with 0 calls after a week of daily use is a candidate to drop or move behind a feature flag.

**Do not**: prune by intuition. "This tool feels useless" is exactly how you delete the one tool the user quietly relied on. The tool-usage counter is authoritative; use it.

## T-latency-optimization (data-gated: multi-turn spread)

**What's blocked**: the one live Phase 4C measurement (~8.2s wake-to-first-audio, warm, single sample) pointed at the Planner LLM's first-token time as the fat hop (~2s). Whether the FIX is a faster LLM (Haiku 4.5), a smaller Planner prompt, or a routing split depends on whether that 2s is steady state or an artifact of one warm sample.

**What we need before touching this**: run `/diagnostics/latency?n=20` after a day of use. Look at the spread of `planner_first_token` and `context_ready` values across cold + warm + tool-calling + no-tool turns. If planner_first_token is consistently 1.5-3s → LLM swap is the lever. If it's 5-15s → the Planner prompt is too long and needs trimming. If context_ready spikes on cold turns → cache warming strategy.

**Do not**: optimize on principle. One warm sample says one thing; a spread might say something else entirely.

## T-daily-drive-findings (opened as a placeholder)

**Placeholder** for whatever actually breaks or annoys during a real day of use. This ticket exists to remind future-me that "real usage" is the thing that produces new tickets — not more spec-reading. When you come back from using it, log the actual findings here and turn each into its own ticket.
