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

> **UPDATE 2026-07-19 — NEEDS RE-SCOPING. A much simpler bug was found underneath this one and may account for some or all of the symptoms.**
>
> See **T-planner-turn-stale** below. The current question was never reaching the Planner at all from turn 2 onward: Commander snapshotted history *before* adding the current turn, and the Planner dropped `user_query` whenever history was non-empty. The model was answering the previous question because the current one was literally absent from the prompt.
>
> Re-read both symptoms recorded here in that light:
> - *"'what windows are open' triggered `get_stock_price` because the prior turn was about AAPL"* — consistent with the model never seeing "what windows are open" and simply continuing the AAPL turn.
> - *"after several clarification replies accumulated in STM, V3 pattern-matched and hallucinated a rejection"* — also consistent with the model being asked nothing and continuing the visible pattern.
>
> **Do not act on the `[-5:]` capping or prompt-engineering fix direction until this is re-observed on the fixed code.** Both were reasoned from the assumption that the model saw the question and was distracted by history. That assumption was wrong. Re-run the original repros; if they no longer reproduce, close this ticket rather than fixing it.

## T-planner-turn-stale (opened + FIXED 2026-07-19)

**The bug**: the assistant answered the PREVIOUS question on every turn after the first.

```
Q: what is the capital of France        A: (empty)
Q: what is the tallest mountain         A: Paris                          <- Q1's answer
Q: how many legs does a spider have     A: Paris ... Mount Everest ...    <- Q1+Q2's answers
```

**Root cause, two halves — either alone reproduces it:**

1. `commander.py` — `agent_context.recent_conversation = context.render()` ran *before* `context.add_user(text)`, so `history` excluded the question being asked.
2. `planner.py` — message assembly was `if history: extend(history) else: append(user_query)`. Once history was non-empty, `user_query` was dropped **entirely**.

Turn 1 worked because empty history hit the `else` branch. **That is why 200 passing tests never caught it — every one was single-shot.**

**Fix**: Commander is now the single source of truth and adds the current turn *before* snapshotting, so `history` always ends with the question. The Planner appends `user_query` defensively only when it is absent from history — checking the whole history, not just the last message, because Commander's tool loop appends corrections and tool results *after* the question.

**Why not the reverse** (history = prior turns only, Planner always appends): Commander's retry loop mutates `history` in place with assistant/correction pairs. A question appended after those would land out of order.

**Regression cover**: `tests/test_multi_turn_context.py`. The load-bearing assertion lives *inside the mock* — it verifies the messages the Planner actually sends end with the current question. A mock returning a canned string would pass even with the bug present. Verified by re-introducing the bug: 3 of 4 tests fail with `expected last user message 'what is the tallest mountain in the world', got 'what is the capital of France'`.

**Found by**: the AI Core telemetry panel. The em-dashes were not a panel failure — they were the panel correctly reporting that nothing was being published, which prompted the first real end-to-end multi-turn probe of the session.

## T-ai-metrics-stream-path (opened + FIXED 2026-07-19)

**The bug**: `ai_metrics` never fired for the agent. `_emit_metrics` was called only from `provider.py` inside `generate()`; `chat_stream()` had zero calls — and the Planner streams exclusively. Consequence: AI Core's Model / Tok/s / Latency / Infer rows and BottomBar's LATENCY were permanently em-dash, and the status pill could never leave "Standby".

Same class as the phantom-publisher finding, one layer deeper: the publisher existed but sat on a code path nobody called.

**Fix**: `chat_stream()` now accumulates streamed tokens and emits once on completion (never per chunk), including on the fallback path with the fallback backend's name. Skipped on failure so a dead stream isn't reported as throughput.

**Known cosmetic gap — FIXED 2026-07-19**: `active_model` reported the *backend* name (`ollama_cloud`) rather than the model, so the UI's MODEL row named the routing key. `LLMBackend` gained an optional `active_model_name()`; the provider reads it through a defensive `_model_label()` helper (getattr, not a direct call) so duck-typed backends that don't implement it degrade to the routing key instead of raising mid-request. Verified live: `model=gpt-oss:120b`.

**Still open**: two planner LLM calls fire per conversational turn (observed 2641ms + 3859ms), so the panel shows whichever landed last and Tok/s reads jumpy. Cause not yet established — the JSON-parse retry path in `planner.py` is the leading hypothesis. Measurement may also be contaminated by T-wake-word-executes-ambient-audio.

## T-agent-reasoning-conversational (opened + FIXED 2026-07-19)

**The bug**: `AgentReasoningEvent` was published only in the `tool_calls` branch of `planner.py`. The `final_response` branch returns before reaching it, so conversational answers — most turns — emitted no reasoning and the UI ticker stayed blank.

**Fix**: publish a short honest line on the `final_response` branch too. Deliberately not the answer text: the ticker is one truncated line and the answer already surfaces elsewhere.

## T-planner-canvas-chain (opened 2026-07-09, re-classified 2026-07-10)

**The bug**: On canvas requests, the user asks to render a widget and gets a spoken text answer instead.

**Classification (from `tools/canvas_chain_probe.py`, 9 runs across 3 phrasings)**:
- Turn 1 chains fine — V3 emits both data-fetch tools (`get_stock` + `get_news_data`) in one response, 9/9.
- Turn 2 renders correctly 7/9. The other 2/9 V3 emits `final_response` claiming *"I've displayed on your canvas"* without actually calling `render_canvas`. Silent hallucinated completion, worst failure mode.
- Root cause is **not** a Planner prompt gap and **not** a planner-loop / chaining gap. It's Commander's iteration-2 instruction at `backend/core/agents/commander.py:172-174`: `"Summarize results for the user."` — that cue shades V3 toward a natural-language summary, which some fraction of the time becomes a fabricated render claim.

**Fix direction**: Commander should detect canvas-intent in the original user query and swap the iteration-2 instruction from `"Summarize results for the user."` to something like `"Now call render_canvas with widgets built from these tool_results. Do NOT emit final_response until render_canvas has actually been called."` Alternatively (or additionally), harden the Planner system prompt: `"Never emit final_response claiming a canvas was rendered unless render_canvas was actually called in this same response."` The Commander change is the tighter fix — the Planner change is a safety net.

**Regression probe**: `tools/canvas_chain_probe.py` (untracked). Reruns cheap. After any fix, target is turn-2 render_canvas at 9/9 across all three phrasings.

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

## T-rule-tier-overmatch (opened 2026-07-19 — FIXED, pending review)

**The bug**: two compounding defects made the rule tier intercept queries it
shouldn't, and corrupt the ones it should.

**Defect A — `normalize()` is a cache-key normalizer that was also used as
rule-engine input.** It strips all of `string.punctuation` before the text
reaches `rule_engine.match()`, destroying arithmetic operators and URL
structure:

| Input | After normalize | Resolved as |
|---|---|---|
| `calculate 2+2` | `calculate 22` | `calculate('22')` — **returned 22** |
| `what is 15 * 3` | `what is 15 3` | `calculate('15 3')` |
| `open github.com` | `open githubcom` | `open_app('githubcom')` |
| `open localhost:3000` | `open localhost3000` | `open_app('localhost3000')` |

Both URL rules require a literal `.` in the domain, which normalize always
removed — **confirmed unreachable dead code** (0 matches on every URL probe).
The calculator could never receive a valid expression. The LLM path was
unaffected: `router.py` passes raw `text`, not the normalized form.

**Defect B — greedy `.+` catch-alls reachable via the fallback scan.**
`^(?:calculate|what\s+is|what's)\s+(?P<expr>.+)$` claimed any question
starting with "what is". Measured interception on a 15-question sample:
**11/15**.

The prefix trie did not prevent this. `_build_trie` extracted only the
**first** alternative of a pattern, so the calculator bucketed under
`"calculate"` and a "what"-prefixed query missed it in the fast path — but
`match()` then ran a **full linear scan over every rule**, giving greedy
patterns a shot at every input anyway. The trie was a fast path, never a
filter.

`router.py` then cached the bad match, so it repeated.

**Why it mattered**: rule mis-matches are worse than errors. A 502 signals
failure; `calculate('your opinion on jazz music')` returns a confident wrong
answer. It was masked by the OpenRouter 402 — everything reaching the LLM
tier failed anyway, so mis-routes looked like the only path that worked.

**Fix applied**:
1. Added `normalize_for_rules()` — lowercases, collapses whitespace, strips
   only trailing `.?!` and surrounding quotes. `normalize()` is unchanged;
   cache entries and other callers depend on its behavior. `router.py` now
   computes both and uses each for its own purpose.
2. Rewrote `_build_trie`'s token extraction to expand **all** leading
   alternatives, including nested optional groups (`what(?:'s| is)?` →
   `{what, what's}`). Catch-all rules dropped from 7 to 4, and the remaining
   4 are genuinely undeterminable (bare-URL, bare-arithmetic).
3. Removed the fallback linear scan, after verifying trie-only ≡ trie+fallback
   across a 67-input corpus (0 divergences).
4. Constrained the greedy patterns: `what is`/`what's` now require an
   arithmetic-looking target (`calculate X` stays permissive — the explicit
   verb is a clear signal); `summarize` requires a URL or a file with an
   extension; `open_app` requires a known alias or single bare token and
   drops the `start` verb; `remind me` requires `to` or a trailing duration.
   `play` and `search` deliberately left alone.

**Regression corpus**: `tests/test_rule_tier_routing.py`, 33 cases asserting
action AND target. Suite went 160 → 193 passing.

**Known follow-up**: one pre-existing test asserted the buggy behavior
(`_check_rule("summarize this article", "summarize_pdf")` in
`tests/test_all_phases.py`) and was updated, with the original quoted in a
comment.

**Suspected contamination of earlier findings**: some of what
`T-planner-context-bleed` recorded as planner misbehavior may have been
queries that never reached the planner.

### T-rule-tier-overmatch — follow-up: apostrophe regression (2026-07-19)

The fix above inverted which apostrophe spelling worked, because the rules
had always disagreed and `normalize()` was hiding it by stripping
apostrophes so every form collapsed to `whats`.

- Five rules used `what(?:'s| is)?` — accept `what's` / `what is`, reject
  `whats`: weather, forecast, news, battery, calculator.
- One rule used a bare `whats` — accepts `whats`, rejects `what's`: time.

Pre-fix everything normalized to `whats`, so the time rule worked and the
other five did not. Post-fix apostrophes survive, so the five worked and
**`what's the time` broke** — plausibly the single most-used voice command
on this HUD.

`_token_variants` handled this at the trie-bucketing layer, making a pattern
*findable* under both spellings, but the regex itself still matched only one
— and with the fallback scan removed there was no second chance. Right
instinct, wrong layer.

**Fix**: made the apostrophe optional in the regex at all six sites
(`what(?:'?s| is)?`, `what'?s\s+the\s+time`). Also taught `_expand_states`
that a `?` after a single character makes that character optional, so
`what'?s` buckets under both `what's` and `whats` instead of silently
degrading to a catch-all.

**Consequence**: `_token_variants` is now fully redundant — the trie is
byte-identical without it and it contributes zero unique buckets. Left in
place pending a decision rather than deleted.

**Why the corpus missed it**: all 33 original cases used exactly one
spelling each, so the disagreement was invisible. Added `APOSTROPHE_PAIRS`,
which asserts *pairs* rather than spellings. Suite 193 -> 200.

**Also found**: `.venv/Scripts/python.exe -m pytest` reports "No module
named pytest" — the project's own venv cannot run the project's own tests,
so anyone following the README's `.venv\Scripts\activate` -> `pytest` path
hits a wall. pytest exists only in the system interpreter.

## T-wake-word-executes-ambient-audio (opened 2026-07-19 — PARTIALLY MITIGATED)

**Observed**: during an unrelated HTTP query, the daemon executed `open_app` → "opened Terminal". The HTTP response's `tool_records` was `[]`, so it did not come from the request. The mic listener acted on ambient audio.

**The "no wake gate" hypothesis is WRONG.** All three trigger paths in `wake_word.listen()` require a wake or a state derived from one:

1. **Wake phrase** (`wake_word.py:278`) — requires `"onyx"` in the Vosk partial. Correctly gated.
2. **Follow-up** (`:284-288`) — `elif in_followup: if rms > 500`. `followup_until` opens for `_FOLLOWUP_WINDOW_S = 3.0` after a *successful* command. Requires a prior turn, but **within that 3s window mere loudness triggers a capture** — no phrase required.
3. **Barge-in** (`:296-300`) — requires `state_manager.current == SPEAKING` plus `rms > 800` for 2 consecutive frames.

**The actual defect is a self-sustaining feedback loop, not a missing gate:**

```
legitimate wake -> assistant SPEAKS (TTS)
                -> speaker bleeds into mic
                -> barge-in fires (state==SPEAKING, rms>800)
                -> captures TTS + room tone
                -> Whisper hallucinates a transcript
                -> dispatched to router and EXECUTED
                -> assistant speaks the result -> loop repeats
```

Each completed command also opens a 3s window where loudness alone re-triggers. So **one legitimate wake can cascade into an unbounded chain of misheard commands.** The code already admits the seed condition at `wake_word.py:293-295`: *"a loud speaker close to the mic will still false-fire (out of scope — future AEC work)."*

**Why it reached execution**: `trigger.py` validated only `rms < 200` before dispatch — loudness, not speech. `command = (stt.get("text") or "").strip()` then went straight to `_process_and_execute` with **no check that it was non-empty or plausible**. Corroborating evidence from earlier the same session: a stray `command_transcribed` carrying `"The assistant controls notepad, chrome, firefox, vscode, ive,"` — a Whisper hallucination that would have been dispatched.

**Mitigation applied**: `_is_dispatchable()` in `trigger.py` drops empty, whitespace-only, sub-2-character, and known-Whisper-hallucination transcripts (`"you"`, `"thank you"`, `"thanks for watching"`, `"[BLANK_AUDIO]"`, `"music"`, …) before they reach the router. Covered by `tests/test_transcript_gate.py` (23 cases).

**This is a floor, not a fix.** It breaks the common cascade but a plausible-sounding mis-transcription of real ambient speech still executes. Remaining work, roughly in order of value:

1. **Suppress TTS echo** — track recently-spoken text and reject transcripts that substantially match it. Cheapest real break in the loop; no AEC needed.
2. **Gate the follow-up window on content, not loudness** — `rms > 500` inside a 3s window is far too permissive.
3. **Require confirmation for state-changing tools** when a turn originated from barge-in or follow-up rather than an explicit wake phrase.
4. **Acoustic echo cancellation** — the real fix, already logged as out of scope.

**Not verified**: no live multi-minute ambient-audio observation was run. The gate is unit-tested only.
