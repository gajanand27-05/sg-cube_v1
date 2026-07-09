# Open tickets

One-line trackers for known bugs / open threads. Longer than a line means it's not a ticket anymore, it's a document.

## T-planner-arg-hallucination (Phase 3 fallout, high visibility)

**The bug**: Planner (Gemini 2.5 Flash) called `get_stock(ticker=...)` when the tool declares `symbol=`. End result: the headline demo "show me AAPL on the canvas" doesn't work — model apologizes asking for the symbol you already gave, then Gemini 429s and can't retry.

**Why it doesn't have a fix yet**: prompt-discipline bug, not architecture. LLM behavior around argument-name discipline changes between models. Fix belongs with the DeepSeek V3 migration (memory: `project_llm_migration`) — re-baselining the Planner prompt anyway. Fixing it against Gemini and re-tuning for DeepSeek would be double work.

**Optional band-aid** (independent of migration, one line): accept `ticker` as an alias for `symbol` at the `get_stock` boundary. Not a fix — the model should read schemas correctly — but it's cheap and unblocks the demo now.

**Discovered**: Phase 3 live smoke test, 2026-07-09.

## T-echo-cancellation (Phase 4 out-of-scope, may resurface)

**Placeholder** for the "real acoustic echo cancellation" thread that Phase 4's barge-in spec explicitly punts on. If the room-quiet threshold/debounce turns out to be insufficient in real use, this becomes a real ticket.
