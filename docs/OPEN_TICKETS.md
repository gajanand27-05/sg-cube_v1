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
