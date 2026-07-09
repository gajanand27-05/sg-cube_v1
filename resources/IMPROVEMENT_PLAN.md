# SG_CUBE Improvement Plan

Based on analysis of [FRIDAY](https://github.com/SAGAR-TAMANG/friday-tony-stark-demo) and [Jarvis](https://github.com/sukeesh/Jarvis).

---

## Phase A — Critical Bug Fix (0.5 day)

**A1: Fix tool registry bootstrap**
- `backend/core/tools/builtins.py` is never imported in production — REGISTRY is empty at runtime.
- Add `from backend.core.tools import builtins` in `backend/core/tools/__init__.py` or `backend/core/agent/agent.py`.
- **Effort**: 1 line. **Priority**: P0 (silent failure).

---

## Phase B — Plugin Auto-Discovery (1 day)
*From Jarvis*

- Replace manual `@tool` + REGISTRY dict with `pkgutil.iter_modules('backend/core/tools')` auto-import at boot.
- Add `plugins/` user directory where anyone drops a `.py` with `@tool` decorators — zero config.
- **Files**: `backend/core/tools/registry.py`, `backend/core/tools/__init__.py`
- **New**: `backend/plugins/` directory
- **Effort**: 1 day. **Priority**: P2

---

## Phase C — Real-Time Streaming Voice Pipeline (3-4 days)
*From FRIDAY*

**C1: Streaming ASR**
- Replace VAD-capture→WAV→Whisper with streaming Whisper via `faster-whisper`'s segment iterator.
- Add `silero-vad` for accurate VAD instead of RMS thresholding.

**C2: Streaming TTS with interrupt**
- Piper's `voice.synthesize()` already returns an iterator. Play first chunk while rest synthesizes.
- New wake word immediately cuts off current speech.

**C3: LiveKit Agents as optional voice mode**
- Add `VOICE_PIPELINE=local|livekit` env switch.
- LiveKit handles: STT streaming, VAD, turn detection, endpointing, TTS streaming, interrupt — all out of the box.
- **Effort**: C1-C2: 2d, C3: 2d. **Priority**: P1 (C1-C2), P2 (C3)

---

## Phase D — Fast-Path Command Routing (1 day)
*From Jarvis*

**D1: Expand regex rule engine from 11 → 40+ patterns**
- Add: volume, brightness, weather, news, screenshot, lock, mute, shutdown, reminders, translate, summarize, calculator, dictionary, battery, network status, etc.

**D2: Priority prefix trie**
- Replace linear regex iteration with a trie for sub-millisecond matching.

**D3: Cache normalization + fuzzy aliases**
- Levenshtein-distance cache matching for typos.
- Expand APP_ALIASES from 30 → 100+.

**Effort**: 1 day. **Priority**: P1

---

## Phase E — MCP Protocol Integration (2 days)
*From FRIDAY*

**E1: Expose SG_CUBE tools as MCP server** via FastMCP + SSE.
**E2: Consume external MCP servers** (filesystem, GitHub, etc.).
- **New file**: `backend/core/mcp_server.py`
- **Dependency**: `fastmcp`
- **Effort**: 2 days. **Priority**: P3

---

## Phase F — Games & Personality (1 day)
*From Jarvis*

**F1: 6 CLI games** — Blackjack, Hangman, Wordle, Tic-Tac-Toe, Connect Four, RPS.
**F2: Random generators** — password, coin flip, dice roll, local jokes/facts.
**F3: Mood responses** — "I'm bored" triggers activity suggestion or game.
- **New**: `backend/core/tools/games/`
- **Effort**: 1 day. **Priority**: P3

---

## Phase G — Observability & Developer Experience (1 day)
*From Jarvis's community patterns*

**G1: Latency waterfall dashboard** at `/diagnostics`.
**G2: Tool usage heatmap** in Agent Inspector.
**G3: Plugin development tutorial** with `custom/hello_world.py` example.
- **Effort**: 1 day. **Priority**: P3

---

## Effort Summary

| Phase | Feature | From | Effort | Priority |
|-------|---------|------|--------|----------|
| A | Fix tool registry bootstrap | — | 0.5d | **P0** |
| C1-C2 | Streaming ASR + TTS + interrupt | FRIDAY | 2d | **P1** |
| D | Fast-path routing (40+ patterns) | Jarvis | 1d | **P1** |
| B | Plugin auto-discovery | Jarvis | 1d | **P2** |
| C3 | LiveKit optional voice mode | FRIDAY | 2d | **P2** |
| E | MCP protocol | FRIDAY | 2d | **P3** |
| F | 6 games + personality | Jarvis | 1d | **P3** |
| G | Latency dashboard + dev docs | Both | 1d | **P3** |

**Total**: ~10.5 days

**Recommended sprint order**: A → D → C1-C2 → B → F → C3 → E → G
