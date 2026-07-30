
# SG Cube — Leftovers / Deferred Items

Created 2026-07-30. Deferred work and the don't-ship list.

**Bugs do not belong here.** `docs/OPEN_TICKETS.md` is the ticket file; this one
turning into a second one is how a bug gets lost. The B1/B2/B3 entries that were
here have moved:

| was | now |
|---|---|
| B1 — TTS speaks raw planner JSON | `T-tts-speaks-planner-json` — **fixed** 2026-07-30 |
| B2 — `speak_stream` globals vs `asyncio.run` | `T-tts-loop-globals` — open, recorded |
| B3 — `log.exception` dies on cp1252 | `T-log-cp1252` — **fixed** 2026-07-30 |

Two memory-engine bugs found while investigating this batch are also filed there
rather than here: `T-memory-zero-vectors` (86% of long-term memories have a
zero-norm embedding and are unsearchable) and `T-memory-duplicate-rows`. Both
open, neither fixed. `tools/memory_health.py` is the before/after instrument.

---

## Task 1: TTS Echo Suppression — Remaining Open Items

### E1. End-to-end open-air test (unverified)
- **What**: Full chain: speaker -> air -> mic -> Whisper -> dispatch gate
- **Status**: Both halves proven separately, join never completed on this machine
- **Why blocked**: `stop_speech()` fires barge-in on the first sample, so capture holds only ~200 ms of speech plus silence. Whisper hallucinates on silence → "Sorry about getting ready to talk about it."
- **Fix options** (pick one):
  - **A** — Defer `stop_speech()` until after recording finishes (in `wake_word.py`), or add a flag to delay barge-in
  - **B** — Use a second machine/room: speaker on one side, mic on the other
  - **C** — Enable Stereo Mix loopback and route playback back through the capture path (won't reproduce real acoustics but closes the loop)

### E2. Stereo Mix device 16 is disabled
- **How to enable**: Sound control panel (already opened via Run → `mmsys.cpl`) → right-click "Show Disabled Devices" → right-click "Stereo Mix (Realtek HD Audio Stereo input)" → Enable
- **Why it matters**: Would let the e2e probe capture its own playback without a second room
- **Current workaround**: WASAPI Primary Sound Capture (device 4) works for recording but driver doesn't route playback to it

### E3. Loopback test skips instead of fails
- **What**: `test_e2e_echo_loopback.py::test_e2e_loopback_captures_playback` is currently `pytest.skip()` on this hardware
- **Impact**: No broken tests, but the capture path isn't unit-testable here
- **Fix**: Either keep the skip with the explanation (current) or make the test conditional on a device query at import time

---

## Files Not To Be Shipped

### Tools (manual probes only)
- `tools/e2e_echo_probe.py` — Manual e2e loopback probe script. Intended for local debugging, not part of the production codebase.

### Tests (verification, not shipped)
- `tests/test_e2e_echo_loopback.py` — E2E loopback probe. Requires hardware loopback access (sounddevice). Won't run on CI or production.
- `tests/test_tts_echo_suppression.py` — 19 tests for echo matcher logic. Pure unit tests, no hardware. Could ship but they're tied to the echo suppression feature which is already covered by the non-test changes.
- `tests/test_memory_hit_event.py` — Tests for MemoryHitEvent serialization and publish. Pure unit tests.

### Probe/Debug-only
- `_query_devices.py` → **already deleted** (leftover from device enumeration)

### Config / Docs
- `plan.md` — Project plan. Intended for dev reference. Consider placing under `docs/` or a `DEVELOPER.md` in a shipped repo.
- `AGENTS.md` — Your opencode/agent instructions. Not needed in a production repo.

### Recommendation
Ship all `tests/` files — they're the proper place for unit tests. Move `tools/e2e_echo_probe.py` to `docs/` with a note that it's a manual probe, or delete if the e2e test covers it. Keep `plan.md` or `AGENTS.md` only if the repo will continue to be iterated on locally.
