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

**~~Still open~~ — CLOSED 2026-07-30, hypothesis killed**: this claimed two planner LLM calls per conversational turn (observed 2641ms + 3859ms), with the JSON-parse retry at `planner.py` as the leading suspect. **Those figures are formally retracted** — they were measured while the wake-word daemon was live and executing misheard audio, so ambient turns were mutating the same shared state.

Re-measured on the text path with `enable_wake_word=False`, instrumenting `LLMProvider.chat_stream` call counts, `PlannerAgent.generate_plan_stream` invocations and `_emit("retrying_parse")` separately so the two candidate causes were distinguishable:

- **1.00 planner LLM calls per turn**, distribution `{1: 10}` over n=10 plain conversational turns. Not one turn made a second call from *any* component.
- **0/10 corrective JSON retries**, 0/10 turns with more than one planner invocation.
- **0.0% failure rate** on n=12 trivia questions (0 hard failures, 0 wrong/evasive).

The retry path exists and is reachable; `gpt-oss:120b` simply returns clean JSON. The original observation was on the OpenRouter/DeepSeek stack that no longer exists — most likely model-specific JSON malformation, but that is untestable now and not claimed.

Recorded here rather than left in commit `dc6349f`'s message, where it was invisible to anyone reading the ticket.

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

1. ~~**Suppress TTS echo**~~ — **DONE 2026-07-30** (commit `dc6349f`). `speak_stream()` records every utterance; `was_recently_spoken()` matches a transcript by token containment against the live speaking burst; `trigger.py:409` drops matches with `dropped TTS echo: %r`. Live-verified at the dispatch point. The open-air join is still unproven — see E1 in `leftovers.md`.
2. **Gate the follow-up window on content, not loudness** — `rms > 500` inside a 3s window is far too permissive. **Now the top remaining item**: with echo suppression in, the observed live failures were Whisper hallucinating on near-silence after `stop_speech()` truncated the capture (`'Sorry about getting ready to talk about it.'`, `'I am working out.'` — the latter ran a full LLM turn). Those are not echo and this gate is what would stop them.
3. **Require confirmation for state-changing tools** when a turn originated from barge-in or follow-up rather than an explicit wake phrase.
4. **Acoustic echo cancellation** — the real fix, already logged as out of scope.

**Not verified**: no live multi-minute ambient-audio observation was run. The gate is unit-tested only.

## T-panel-listener-state-lost-on-remount (opened 2026-07-19)

**Observed**: after a live query, the AI Core panel showed MODEL / TOK/S / LATENCY / INFER / REASONING populated, but CONFIDENCE, LAST RESPONSE and the tier counters blank — all from the same turn.

**Mechanism**: an asymmetry between the two subscription hooks in `useUiEvents.ts`.

| Hook | Seeds from `latest` on mount | Survives remount |
|---|---|---|
| `useUiEvent` (:196-203) | yes | yes |
| `useUiEventListener` (:208-217) | no | **no** |
| `useUiEventCounter` (:222-229) | no | no |

Listener-backed values live in component `useState`, so they are gone permanently on remount while `useUiEvent` rows recover from the module-level cache.

**Trigger is a remount, NOT a stale page.** `latest` is a module-level Map, so a full page refresh clears it too — MODEL/TOK/S would also be blank in that case. They were populated, so the events did arrive while mounted. The realistic causes are StrictMode double-mount, or HMR updating `AICorePanel.tsx` while leaving `useUiEvents.ts` (and therefore `latest`) intact — likely, since the frontend was being edited all session.

**Isolating test** — one step, and it distinguishes this from "events aren't arriving":
1. Ask a question, confirm CONFIDENCE fills with a bar.
2. Touch any frontend file to trigger HMR.
3. CONFIDENCE goes blank while MODEL / TOK/S survive.

Note the naive test (ask another question with the panel open) passes and confirms the wrong thing — it proves events flow, not that state survives a remount.

**Do NOT fix by seeding `useUiEventListener` from `latest`.** `useUiEventCounter` shares the same `subscribe()` (:227) and increments on each callback, so replaying the last cached event on mount would inflate the tier counters on every hot reload.

**Fix direction**:
- CONFIDENCE -> `useUiEvent("agent_completed")?.confidence`. Already cache-seeded, no new machinery.
- LAST RESPONSE -> needs an arrival time. The envelope carries `timestamp` (stamped server-side at `ws_ui.py:105`, typed in `uiEvents.ts`) but `useUiEvent` discards it at :203 (`setPayload(env.payload)`). Either add a `useUiEventEnvelope` variant or let `useUiEvent` optionally return the envelope.

**Also correct a comment while in there**: the tier counters are documented as "session-only ... a runtime diagnostic". They are actually *since-last-mount* and reset on every HMR update. The behaviour is fine; the comment overclaims.

**Found by**: the panel diagnosing itself.

## T-tts-speaks-planner-json (opened + FIXED 2026-07-30)

**Observed**: on every streaming voice turn the assistant read its own JSON envelope aloud. The recent-spoken ring (added for echo suppression, so it records exactly what Piper was handed) captured `'{"final_response":"Got it!'` and `'...anything else!"}'` as separate spoken utterances.

**Mechanism**: Phase 4B streams the Planner's tokens to TTS a sentence at a time to cut time-to-first-audio. `brain.py:99-108` accumulated raw Commander `token` chunks into `sentence_buffer` and fired `tts_ready` whenever `_is_sentence_complete()` (`brain.py:139-142`) matched `[.!?]\s*$` with length > 10. But the Planner emits a serialized envelope, not prose, so the punctuation that predicate tripped on was **JSON punctuation**. The clean text existed only at the `final_response` branch (`brain.py:117`), by which point the garbage was already queued to Piper.

Not a predicate bug. The predicate was correct for its stated input; the input was never prose. Phase 4B's streaming assumption and the Planner's output contract disagreed, and nothing sat between them.

**Fix**: `backend/core/agents/prose_stream.py` — `FinalResponseExtractor`, a character state machine that incrementally pulls the `final_response` string value out of the token stream (handles `\"`, `\\`, `\n`, a split `\uXXXX`, a ```json fence, and prose prefixed before the envelope). The Planner feeds each token through it and yields a distinct `prose` chunk for whatever became speakable; Commander forwards it as `CommanderChunk("prose", ...)`; `brain.py` buffers **only** prose for `tts_ready`. Raw `token` chunks still flow untouched so the UI ticker and the `planner_first_token` latency mark are unaffected.

Deliberately not a JSON parser: waiting for a complete document would hand back the whole Phase 4B win. Deliberately not sanitizing `{`/`}` out of `sentence_buffer` downstream — that treats the symptom and breaks on the next format change.

A `tool_calls` envelope yields no prose at all, which is correct: those turns speak after execution. Previously they queued raw JSON here too, and `brain.py:130` used the leftover buffer as `spoken_text`.

**Verified live**, three real turns (real LLM, Planner, Commander, Brain, SentenceQueue, Piper, audio out), reading back the recent-spoken ring and replaying the old predicate over the same token stream:

| turn | envelope fragments spoken, before | after |
|---|---|---|
| "tell me about the planet Jupiter in three sentences" | 1 | 0 |
| "hello there" | 1 | 0 |
| "what is the capital of France" | 1 | 0 |

**Time-to-first-audio**, same turns, `wake -> first_audio_out`: unchanged on the multi-sentence turn (6058ms -> 6058ms), **+74ms** on "hello there", and *faster* on "what is the capital of France" (the old predicate never matched at all — the buffer ended `."}` — so that turn only spoke via the end-of-stream fallback; it now streams at 4350ms). Max regression observed 74ms.

**Known gap**: on the JSON-parse corrective retry (`planner.py`), prose streaming is suppressed for the second attempt — attempt 1 may already have voiced part of a value that then failed to parse, and re-emitting would speak the answer twice. That turn falls back to speaking the full parsed reply, costing one turn's streaming. The retry path fired 0/22 times when last measured.

**Tests**: `tests/test_planner_prose_stream.py` (20). Note these prove the extractor and the wiring only — an assertion that `tts_ready` contains no `{` passes happily while the speaker stays broken. The ring read-back above is the pipeline evidence.

## T-tts-loop-globals (opened + FIXED 2026-07-30)

**Observed**: during live probing, two overlapping voice turns produced `got Future <Task ... _audio_player()> attached to a different loop`, then `'NoneType' object has no attribute 'put'` from `speak_stream`, then `'NoneType' object has no attribute 'set'`. Playback died mid-turn.

**Mechanism**: `handle_wake()` (`trigger.py:153`) runs `asyncio.run(...)` — a **fresh event loop per capture**. But `tts_piper.py` keeps `_audio_queue`, `_stop_event` and `_playback_task` at module scope, and clears them to `None` in `speak_stream`'s `finally`. So turn B's loop adopts turn A's queue while turn A's `finally` nulls the globals underneath it. `tts_queue.py`'s own module docstring already names the hazard: *"overlapping speak_stream() calls would race"* — `SentenceQueue` serializes within a turn, which is why this only shows up across turns.

Reachable in production, not just under probing: barge-in starts a new capture (and therefore a new `asyncio.run`) while the previous turn's playback is still unwinding.

**Fix**: per-call playback state. `_PlaybackSession` (queue + stop flag + player task) is created inside `speak_stream` and bound to that call's loop; the module only remembers which session is *current*, for `stop_speech()`/`is_speaking()` to act on. `finally` stops its own session and releases the slot only if a newer session has not already claimed it — nulling shared globals there is precisely what broke the overlapping case.

The stop flag is a `threading.Event`, not an `asyncio.Event`: barge-in calls `stop_speech()` from the wake-word listener thread, and `asyncio.Event.set()` is not thread-safe — it would mutate state owned by another loop. `stop_speech()` no longer drains the queue either; that is the player's own `finally`, on the player's own loop.

**Chose per-call state over one long-lived daemon loop.** The single-loop option would also have fixed this, but `_audio_player` calls `stream.write()`, which blocks for the duration of the audio. Moving playback onto the server's event loop would have blocked the web server for the length of every spoken sentence — trading an intermittent crash for a guaranteed stall. Per-call state keeps playback on the caller's own loop.

**Barge-in latency is unchanged.** New sessions do *not* wait for the previous one: `_activate()` sets the old session's stop flag and returns, so newest speech wins immediately. Serializing turns behind in-flight playback would have traded a crash for a worse feel, which is the opposite of what barge-in is for. `stop_speech()` is still synchronous and still calls `sd.stop()`.

Also fixed on the same defect: `SentenceQueue.start()` now rebuilds its `asyncio.Queue` instead of draining it. It is a module-level singleton, so the queue built on turn N's loop was bound to a loop closed by turn N+1 — the `<Queue ...> is bound to a different event loop` failure seen from `Brain`. And `tts_queue.py`'s docstring no longer implies that serializing sentences protects against cross-turn overlap; it never did.

**Verified by reproducing first.** `tests/test_tts_concurrent_playback.py` drives two, then four, concurrent `asyncio.run` loops through `speak_stream` behind a `threading.Barrier`, faking only the audio *device* (`sd.OutputStream`) so the loop and state ownership under test stay real. Against the pre-fix code: **2 failed / 4 passed**, with all three original errors — `attached to a different loop`, `'NoneType' object has no attribute 'set'`, `'NoneType' object has no attribute 'empty'`. After: **6 passed**. Real-audio turns re-run afterwards: 0 playback errors, time-to-first-audio unchanged.

**Not verified**: the specific production sequence (HTTP `/voice/say` landing mid-voice-turn) was not staged end to end; the reproduction models it with two loops rather than two entry points.

## T-log-cp1252 (opened + FIXED 2026-07-30)

**Observed**: `trigger crash: 'charmap' codec can't encode character '→' in position 5` — and the actual exception being reported was never logged.

**Mechanism**: `log.exception(f"trigger crash: {e}")` at `trigger.py:425`. On Windows `sys.stdout` defaults to the console codepage (cp1252 here), and the Planner's reasoning strings are joined with an arrow (`planner.py`, `" -> ".join(...)` using U+2192). Encoding the record raised **inside the logging handler**, so the record was dropped. The bug destroys the evidence for whatever bug it was reporting.

**Fix**: `backend/__init__.py` reconfigures `sys.stdout`/`sys.stderr` to `utf-8` with `errors="backslashreplace"`. `reconfigure()` mutates the existing `TextIOWrapper` in place, so handlers that already captured the stream — uvicorn installs its own — are fixed too. `backslashreplace` is the load-bearing half: a write can never raise even where the terminal cannot render the character. No handlers, levels or formats are imposed.

Placed at package import rather than in an entry point because the bug fires from everywhere debugging happens — uvicorn, the daemon CLI, pytest, ad-hoc probe scripts.

**Known scope limit**, found by `tools/memory_health.py` crashing on exactly this: the fix only reaches code that imports `backend`. 25 of 37 `tools/` scripts already do; a standalone script that prints non-ASCII must `import backend` (one line, and the reason is commented at that import).

**Tests**: `tests/test_log_encoding_safety.py` (4), run in subprocesses with `PYTHONIOENCODING=cp1252`. Includes a control that asserts the failure still reproduces *without* the fix, so the test cannot pass by quietly losing its teeth.

## T-memory-zero-vectors (opened 2026-07-30 — WRITE PATH FIXED, DATA REPAIR OPEN)

**Observed**, `tools/memory_health.py`: **32 of 37 rows in `sg_cube_memories` have a zero-norm embedding — 86%.** Only 5 long-term memories in the database are reachable by semantic search at all. `sg_cube_visual` has 3/209. `sg_cube_timeline` cannot be read at all (`InternalError: Error executing plan: Internal error: Error finding id` on `get(include=["embeddings"])`).

**Mechanism**: `long_term.py:28` — when the embedding provider is unreachable, `ProviderEmbeddingFunction` appends `[0.0] * 768` and the row is stored anyway. A zero vector has no direction, so cosine distance to it is degenerate and the row can never rank. The failure is silent: `store()` logs success, `count()` grows, and search quietly returns less than it should. Local Ollama being down for the whole of 2026-07-29 is consistent with the 86%.

**Why it matters beyond retrieval**: the Memory Engine panel reports `total_entries` from `collection.count()`, so the UI shows 37 memories where 5 are usable.

**Write path FIXED 2026-07-30.** `backend/core/memory/embedding.py` now holds one `ProviderEmbeddingFunction` for all three collections — they each carried a near-identical copy of the same defect. It raises `EmbeddingUnavailable` instead of returning zeros, and also rejects a vector that is empty, the wrong width, or all-zero, since a backend answering with junk is the same lost write by another route.

`store()`, `store_observation()` and `record_event()` now catch that distinctly from a real storage error, log ERROR naming the consequence, publish `MemoryWriteFailedEvent`, and **return `bool`** — previously they returned `None` and logged success regardless.

Reads changed too, and this is a quiet improvement: Chroma calls the embedding function for `query()` as well, so searches used to run *with a zero vector* and return arbitrary nearest neighbours. They now raise and degrade to an empty result, which every caller already handles.

**Chose not to reuse `ProviderDegradedEvent`** even though `AICorePanel.tsx:43,112` already consumes it. That panel maps `action: "gave_up"` to status **"Offline"**, so an embedding outage would have claimed the reasoning model was down — a false alarm in the exact place you would look. `MemoryWriteFailedEvent` is a new typed event, mapped in `ws_ui.py`, and the Memory Engine panel shows a red "Write Failed" pill plus a session count of lost writes (hidden entirely at zero, so it reads as an alarm rather than another stat).

**Verified live** against the real database with the embedding backend forced to refuse: all three collections returned `False`, three `MemoryWriteFailedEvent`s were published, and row counts did not move (37 / 209 / 1058 before and after). A `get(where={"source": "probe"})` confirmed the probe row was genuinely absent, not merely uncounted. Reads with Ollama up returned 3 hits, so the raise did not break search. 14 unit tests in `tests/test_memory_write_refusal.py`.

**STILL OPEN — the data repair.** The 32 existing dead rows were deliberately left untouched so this ticket's numbers stay a usable baseline. Sequencing matters: the write path was fixed first because every store while the embedding backend was down made the repair bigger. Repair now runs once, against a store that can no longer re-poison itself.

Before closing: `tools/memory_health.py` must report `zero_vectors=0`. Note the repair needs the embedding backend *up and staying up* — a run that half-fails re-poisons the rows it touches. Verified 2026-07-30 that local Ollama answers a real `embed()` (768 dims, norm 22.8), but that is a point-in-time check, not a guarantee.

## T-memory-duplicate-rows (opened 2026-07-30 — NOT FIXED, recorded only)

**Observed**, `tools/memory_health.py`: 29 duplicate rows in `sg_cube_memories` (37 rows, 8 distinct documents), 39 in `sg_cube_visual`, 290 in `sg_cube_timeline` (1053 rows, 763 distinct). Worst offenders: `'User asked: "what time is it"'` x50, `'User likes dark mode'` x6.

First surfaced by the Memory Engine panel, which showed the same fact 4x in a 5-hit recall — a quarter of the long-term store spent on one preference.

**Mechanism**: `store()` in `long_term.py` calls `collection.add()` with a fresh `uuid4` every time and no content check, so re-stating a fact appends rather than updates. `merge_similar_memories()` exists at `long_term.py:405` and **nothing calls it**.

**Fix direction**: dedupe on write (content hash, or a similarity check against the top-1 nearest neighbour) plus a one-off compaction pass over the existing rows. Note ordering: this is downstream of T-memory-zero-vectors — a similarity-based dedupe cannot work while 86% of vectors are zero, so fix the embeddings first. Confirm with `tools/memory_health.py`.

**The duplicates are not all real memories — a large share is STT junk.** Added 2026-07-30, from `tools/memory_health.py`:

```
 50x  'User asked: "what time is it"'
 20x  'User asked: "Thank you very much."'
 17x  'User asked: "I am using a voice assistant. I am using a voice as...'
 15x  'User asked: "The assistant controls notepad, close chrome, firef...'
 11x  'User asked: "The assistant controls notepad, chrome, firefox, vs...'
```

Rows 2-5 are Whisper hallucinations, not user speech. `"Thank you very much."` is in `trigger.py`'s own `_STT_HALLUCINATIONS` set, and `"The assistant controls notepad, chrome, firefox, vscode, ive,"` is the exact string quoted as corroborating evidence in **T-wake-word-executes-ambient-audio** above. That is ~60+ timeline rows that are the fossil record of the mic executing room noise.

**So the repair is purge-and-merge, not merge alone.** A dedupe pass that only collapses duplicates would faithfully preserve one clean copy of each hallucination. Junk has to be deleted, not deduplicated.

**Is the timeline still recording anything the mic hears?** No longer, on the mic path: `timeline.record_event` is called from `commander.py:139` (`User asked: "..."`), which runs inside `Brain` — downstream of both `_is_dispatchable` (`trigger.py:393`) and the TTS echo gate (`trigger.py:409`). A transcript rejected by either never reaches Commander, so it is never recorded. The historical junk predates those gates.

Two caveats on that: the HTTP `/chat` and proactive paths reach Commander *without* passing `_is_dispatchable`, and the gate is a floor, not a classifier — a plausible-sounding mis-transcription still records.

**Source histogram** of all 1058 rows, for whoever writes the purge: `user_query` 826, `vision` 194, `execution` 29, `manual` 9.

**Baseline was 1054 rows when handed over and is 1058 now.** The growth is this session's own verification turns — every real Brain turn writes one `user_query` row. Worth knowing before the repair: probing the voice path inflates the very table being repaired. `sg_cube_memories` (37) and `sg_cube_visual` (209) are unchanged.

## T-timeline-index-desync (opened 2026-07-30 — UNDIAGNOSED)

**Observed**: reading embeddings from `sg_cube_timeline` fails for the whole collection, not for particular rows:

```
coll.get(include=["embeddings"])
--> InternalError: Error executing plan: Internal error: Error finding id
```

All 1058 rows are unreadable this way, so `tools/memory_health.py` reports `zero_vectors=?` for this collection and cannot tell how much of it is salvageable. `sg_cube_memories` and `sg_cube_visual` read fine.

**This is not T-memory-zero-vectors.** That one is bad *values* written through a bad code path, and the code path is now fixed. This is Chroma failing to resolve ids at all, which reads like the HNSW index being desynced from the metadata store — index-level corruption rather than poisoned content. A zero-vector row still reads back; these do not.

The distinction matters for the repair: the other two collections can be re-embedded in place, but a desynced index may need the collection rebuilt from its documents and metadata, which are still readable (`get()` without `include=["embeddings"]` works — that is how the duplicate counts and the source histogram above were produced).

**Still being written to.** 1053 → 1058 over this session. The writer is `timeline.record_event` from `commander.py:139`, once per Brain turn; `vision_loop.py:87` also writes on the vision path. So the collection is growing while unreadable, and every probe of the voice path adds to it.

**Undiagnosed. Not attempted**: no repair, no rebuild, no root-cause work. Unknown whether writes are also silently failing, whether it is one bad segment or the whole index, and when it started. First step is probably to compare `chroma.sqlite3`'s segment/embedding tables against the collection's id list — the old `_check_chroma_sql.py` probe did exactly that kind of dump before being consolidated away, and is recoverable from git history if useful.
