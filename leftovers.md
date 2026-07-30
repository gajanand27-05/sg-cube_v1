
# SG Cube — Leftovers / Deferred Items

Created 2026-07-30. Tracks items that were acknowledged but not fully completed, plus files not intended for production.

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

## Bugs Found Along the Way (Not in Scope — Not Fixed)

### B1. TTS speaks raw planner JSON to user
- **Where**: `streaming path` in `brain.py` — `brain.run_stream()` yields `tts_ready` chunks that contain JSON envelopes like `'{"final_response":"Got it!'` instead of clean text
- **Impact**: User hears `'{"final_response":"Got it!", "tool_calls":...}'` spoken out loud
- **The clean text** appears in `[ai] response:` logs but the streaming TTS path voices the JSON instead
- **Severity**: Visible to user on every streaming turn

### B2. `speak_stream` globals vs `asyncio.run` per capture
- **Where**: `trigger.py:153` — `handle_wake()` opens a fresh `asyncio.run()` loop for each capture, but `_audio_queue`, `_stop_event`, `_playback_task` are module-level in `tts_piper.py`
- **Impact**: Two overlapping turns → `'Future ... attached to a different loop'`, then `"'NoneType' object has no attribute 'put'"`
- **tts_queue.py docstring already anticipates this**
- **Severity**: Intermittent crash during concurrent speech

### B3. `log.exception` dies on cp1252
- **Where**: `trigger.py:425` — `log.exception(f"trigger crash: {e}")`
- **Impact**: When the real exception contains `→` (arrow) or other UTF-8 characters, the logger itself fails with `'charmap' codec can't encode character '\u2192'`, and the real error is lost
- **Severity**: Silent loss of error context during crashes

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
