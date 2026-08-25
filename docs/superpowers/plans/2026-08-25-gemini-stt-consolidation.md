# Gemini STT Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Whisper with Gemini as the only speech-to-text path, behind Whisper's existing function signature, without touching the five agents or the HUD.

**Architecture:** A new `stt_gemini` module exposes the exact signatures `stt_whisper` exposes today, so `trigger.py` and `voice.py` change one import line each and everything downstream — normalize, rule engine, brain, the five agents, Piper — is untouched. A shared `KeyPool` fronts all Gemini traffic so a key parked by the planner is not immediately retried by STT. Whisper is NOT deleted until a live gate passes; the wire-in sits behind a setting that reverts to Whisper with one config flip.

**Tech Stack:** Python 3.12, `google-genai` 2.10.0, pydantic-settings, pytest, numpy, FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-25-gemini-stt-consolidation-design.md`

## Global Constraints

- **Do not modify anything under `frontend/`.** Hard constraint from the owner. No HUD changes of any kind, including text.
- **Do not modify the five agents** (`backend/core/agents/{planner,commander,guardian,operator,watcher}.py`) or `backend/core/brain.py`.
- **Do not modify `backend/core/orchestrator/rule_engine.py`.** It keeps working, unchanged, on Gemini's transcript.
- **Run tests with `.venv/Scripts/python.exe -m pytest`.** System Python lacks `cv2`/`torch` and fails 5 vision tests for the wrong reason. Bare `pytest` from the repo root is broken.
- **Baseline to hold green: 1025 backend passed, 3 deselected, 17 frontend.** Never commit a red suite.
- **No `Co-Authored-By: Claude` trailer on any commit.** Owner asked emphatically.
- **`google-genai` is 2.10.0.** The async surface is `client.aio.models.generate_content`; the sync surface is `client.models.generate_content`. `generate_content_async` and `models.list_models()` are the OLD `google-generativeai` SDK and DO NOT EXIST. Both this repo and the camera module shipped calls to them and stayed green because the tests mocked the seam.
- **`zoneinfo` has no tz database on this machine** (`ZoneInfoNotFoundError` for `America/Los_Angeles`, `tzdata` not installed). Do not use `ZoneInfo`. Do not add `tzdata`.
- **`httpx` must stay `<0.28`** or supabase breaks.
- **Whisper stays installed and callable until Task 8.** Tasks 1-7 must not delete it.

---

### Task 1: Phase 0 — measure the Whisper baseline

Without a "before" number the latency gate is unfalsifiable. This task produces it and changes no production code.

**Files:**
- Create: `tools/_scratch/stt_baseline.py` (git-ignored — `tools/_scratch/` is in `.gitignore`)
- Modify: `logs.md` (git-ignored)

**Interfaces:**
- Consumes: nothing.
- Produces: baseline numbers recorded in `logs.md`. Task 7 reads them. No importable code.

- [ ] **Step 1: Write the baseline harness**

Reuse the scoring logic already proven in `tools/_scratch/vosk_open_vocab_probe.py`. That probe's `intent_of()` and its per-take handling are correct and were debugged this session — do not re-derive them.

```python
"""Whisper baseline for the Gemini STT migration gate.

Produces the "before" numbers that docs/superpowers/specs/
2026-08-25-gemini-stt-consolidation-design.md section 7.1 rows 1-3 compare
against. Changes no production code.

Run: .venv/Scripts/python.exe tools/_scratch/stt_baseline.py
"""
from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.ai_modules.speech.stt_whisper import transcribe_array  # noqa: E402
from backend.core.orchestrator import rule_engine  # noqa: E402
from backend.core.orchestrator.normalize import normalize, strip_wake_prefix  # noqa: E402

CORPUS = ROOT / "tools" / "_stt_corpus"


def intent_of(text: str):
    """Real production path: strip wake prefix, normalize, match."""
    cleaned = normalize(strip_wake_prefix(text or ""))
    hit = rule_engine.match(cleaned)
    if hit is None:
        return None
    name = getattr(hit, "name", None) or getattr(hit, "tool", None) or type(hit).__name__
    args = getattr(hit, "args", None) or getattr(hit, "parameters", None) or {}
    return (str(name), json.dumps(args, sort_keys=True, default=str))


def load_float32(wav_path: Path) -> tuple[np.ndarray, int]:
    """Match trigger.py exactly: int16 frames -> float32 normalized to [-1, 1]."""
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    arr = np.frombuffer(frames, dtype=np.int16)
    return arr.astype(np.float32) / 32768.0, rate


def main() -> int:
    truth = json.loads((CORPUS / "corpus.json").read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    timings: list[float] = []

    print(f"{'clip':<18} {'verdict':<12} {'ms':>6}  said -> heard")
    print("-" * 100)
    for clip_id, said in sorted(truth.items()):
        wav = CORPUS / f"{clip_id}.wav"
        if not wav.exists():
            continue
        audio, rate = load_float32(wav)
        t0 = time.perf_counter()
        heard = (transcribe_array(audio, rate).get("text") or "").strip()
        ms = (time.perf_counter() - t0) * 1000.0
        timings.append(ms)

        ti, hi = intent_of(said), intent_of(heard)
        if ti is None and hi is None:
            verdict = "both-miss"
        elif ti is None:
            verdict = "FALSE-HIT"
        elif hi is None:
            verdict = "missed-rule"
        elif ti == hi:
            verdict = "MATCH"
        else:
            verdict = "WRONG-RULE"
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"{clip_id:<18} {verdict:<12} {ms:6.0f}  {said!r} -> {heard!r}")

    total = sum(counts.values())
    print("\n" + "=" * 60)
    print("WHISPER BASELINE — paste into logs.md")
    for k in sorted(counts):
        print(f"  {k:<14} {counts[k]:>3} / {total}")
    timings.sort()
    if timings:
        # Distribution, not a single number. A median hides the tail, and the
        # tail is what a user actually notices — one 4s wait per ten commands
        # reads as "it's slow" regardless of what the median says.
        def pct(p: float) -> float:
            return timings[min(len(timings) - 1, int(len(timings) * p))]
        print(f"  transcribe ms: min {timings[0]:.0f}  median {pct(0.5):.0f}  "
              f"p95 {pct(0.95):.0f}  max {timings[-1]:.0f}")
        print(f"  NOTE: clip 1 includes the 2-3s model load. Re-run and use the")
        print(f"        second run's numbers, or drop clip 1 before reading these.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe tools/_scratch/stt_baseline.py`

Expected: 30 rows, then a summary block. First run loads the Whisper model (2-3s) — that cost lands on clip 1 only and should be noted, not averaged in.

**Note:** corpus clips are 6-7s and hold TWO takes each. Whisper returns one concatenated string, so a doubled phrase cannot match the `^...$`-anchored rules. This baseline therefore UNDERSTATES Whisper's rule-match rate exactly as much as it will understate Gemini's — which is fine, because the gate compares the two under identical conditions. Do not "fix" this asymmetrically for one side only.

- [ ] **Step 3: Record the numbers in `logs.md`**

Append a `## Phase 0 — Whisper baseline` section with the summary block verbatim, the date, and the exact command used.

- [ ] **Step 4: Report the distribution to the owner and let THEM set the threshold**

Report min / median / p95 / max. **Do not propose a latency threshold and do not carry the spec's old 400ms figure forward** — it was written before any measurement existed and the owner has explicitly withdrawn it. The threshold is set by the owner after seeing this distribution, and Task 7 cannot be evaluated until they have set it.

State the number plainly whatever it is. If Whisper turns out to be fast, say so — that makes the migration harder to justify, and that is information, not a problem to be managed.

- [ ] **Step 5: Commit**

Nothing to commit — `tools/_scratch/` and `logs.md` are both git-ignored. Verify with `git status --short` that the tree is clean, then move on.

---

### Task 2: `KeyPool` — rotate three keys with correct failure classification

**Files:**
- Create: `backend/ai_modules/llm/key_pool.py`
- Create: `tests/test_key_pool.py`
- Modify: `backend/server/config.py:112-113`

**Interfaces:**
- Consumes: `backend.server.config.settings`.
- Produces:
  - `KeyPool.acquire() -> tuple[int, str] | None`
  - `KeyPool.report_success(slot: int) -> None`
  - `KeyPool.report_failure(slot: int, exc: Exception) -> None`
  - `KeyPool.status() -> list[KeyStatus]`
  - `KeyStatus` dataclass with fields `slot: int`, `configured: bool`, `parked_until: float | None`, `reason: str`
  - module singleton `pool: KeyPool`
  - Task 3 and Task 4 both import `pool`.

- [ ] **Step 1: Add the two new settings**

In `backend/server/config.py`, replace lines 112-113:

```python
    # ── Gemini (Google AI SDK) ──
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
```

with:

```python
    # ── Gemini (Google AI SDK) ──
    # Three keys, tried in slot order. Free tier is metered PER DAY, so one
    # key exhausts in a session; the pool (llm/key_pool.py) rotates and, more
    # importantly, parks an exhausted key until its quota resets instead of
    # retrying it every 60s forever.
    gemini_api_key: str = ""
    gemini_api_key_2: str = ""
    gemini_api_key_3: str = ""
    gemini_model: str = "gemini-2.5-flash"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_key_pool.py`:

```python
"""KeyPool: rotation, and the failure classification the ported original got wrong.

The camera module's APIKeyManager parks ANY failed key for 60 seconds. Free
tier limits are per-DAY, so an exhausted key returns after a minute and fails
again — forever. Once all three exhaust, every turn pays three dead network
calls, retried every minute. These tests pin the distinction.
"""
import time

import pytest
from google.genai import errors as genai_errors

from backend.ai_modules.llm import key_pool as kp


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "k" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_2", "j" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_3", "m" * 20)
    return kp.KeyPool()


def _client_error(code: int, message: str) -> Exception:
    """A ClientError shaped like the SDK's, without needing a real response."""
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, message)
    err.code = code
    err.message = message
    return err


def test_acquire_returns_first_configured_slot(pool):
    assert pool.acquire() == (1, "k" * 20)


def test_acquire_skips_unconfigured_slots(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "")
    monkeypatch.setattr(kp.settings, "gemini_api_key_2", "j" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_3", "")
    p = kp.KeyPool()
    assert p.acquire() == (2, "j" * 20)


def test_daily_quota_parks_for_hours_not_seconds(pool):
    """The whole point of this class. 60s would thrash."""
    pool.report_failure(1, _client_error(
        429, "RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
             "'generate_content_free_tier_requests' PerDay"))
    status = {s.slot: s for s in pool.status()}[1]
    assert status.parked_until is not None
    parked_for = status.parked_until - time.time()
    assert parked_for > 3600, f"daily quota parked only {parked_for:.0f}s"
    assert pool.acquire() == (2, "j" * 20)


def test_per_minute_rate_limit_parks_for_60s(pool):
    pool.report_failure(1, _client_error(
        429, "RESOURCE_EXHAUSTED: Quota exceeded PerMinute"))
    status = {s.slot: s for s in pool.status()}[1]
    parked_for = status.parked_until - time.time()
    assert 30 < parked_for <= 120, f"rate limit parked {parked_for:.0f}s"


def test_server_error_parks_for_60s(pool):
    err = genai_errors.ServerError.__new__(genai_errors.ServerError)
    Exception.__init__(err, "503 unavailable")
    err.code = 503
    pool.report_failure(1, err)
    status = {s.slot: s for s in pool.status()}[1]
    assert 30 < (status.parked_until - time.time()) <= 120


def test_invalid_key_parks_permanently(pool):
    pool.report_failure(1, _client_error(400, "API key not valid"))
    status = {s.slot: s for s in pool.status()}[1]
    assert status.parked_until == float("inf")
    assert pool.acquire() == (2, "j" * 20)


def test_all_parked_returns_none_rather_than_looping(pool):
    for slot in (1, 2, 3):
        pool.report_failure(slot, _client_error(400, "API key not valid"))
    assert pool.acquire() is None


def test_success_clears_the_park(pool):
    pool.report_failure(1, _client_error(429, "PerMinute"))
    assert pool.acquire() == (2, "j" * 20)
    pool.report_success(1)
    assert pool.acquire() == (1, "k" * 20)


def test_expired_park_is_reusable(pool, monkeypatch):
    pool.report_failure(1, _client_error(429, "PerMinute"))
    assert pool.acquire() == (2, "j" * 20)
    real_time = time.time
    monkeypatch.setattr(kp.time, "time", lambda: real_time() + 120)
    assert pool.acquire() == (1, "k" * 20)


def test_never_mutates_os_environ(pool, monkeypatch):
    """The ported original sets os.environ['GEMINI_API_KEY'] on every
    activation — global process mutation from library code."""
    import os
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    pool.acquire()
    assert "GEMINI_API_KEY" not in os.environ
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_key_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.ai_modules.llm.key_pool'`

- [ ] **Step 4: Implement `key_pool.py`**

```python
"""Three Gemini API keys, tried in order, with failures classified correctly.

Ported from the SG-CUBE camera module's APIKeyManager, with its two defects
fixed and its file-based key storage dropped.

The defect that mattered: that version marks ANY failed key unavailable for
60 seconds. Free-tier Gemini limits are metered PER DAY. So a key that has
spent its daily quota comes back off cooldown after a minute and fails again,
forever — and once all three exhaust, every single turn pays three dead
network calls before giving up, retried every 60s. Parking too LONG costs
nothing (the key is genuinely spent); parking too short is the thrash.

Also dropped from the original:
  - base64 "obfuscation" of keys on disk. That is encoding, not encryption,
    and it reads as protection while providing none. Keys come from .env.
  - os.environ["GEMINI_API_KEY"] = key on every activation. Library code does
    not get to mutate global process state.
  - test_connection(), which calls client.models.list_models() — a method that
    does not exist in google-genai 2.10.0 (it is .list()), so it reports every
    valid key as invalid.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.server.config import settings

log = logging.getLogger(__name__)

# Transient failures: a 5xx, a timeout, or a per-minute rate limit.
_SHORT_PARK_S = 60.0

# Google's free-tier daily quota resets at midnight Pacific. Computed as a
# fixed UTC-8 offset ON PURPOSE, not via ZoneInfo: this machine has no tz
# database (ZoneInfo('America/Los_Angeles') raises ZoneInfoNotFoundError, and
# tzdata is not installed). During PDT this parks the key up to an hour longer
# than strictly necessary, which is harmless — the key is exhausted either
# way, and the failure being fixed is parking too SHORT.
_QUOTA_RESET_TZ = timezone(timedelta(hours=-8))

_PERMANENT = float("inf")


@dataclass(frozen=True)
class KeyStatus:
    slot: int
    configured: bool
    parked_until: float | None
    reason: str


def _next_quota_reset() -> float:
    """Unix seconds at the next midnight UTC-8."""
    now = datetime.now(_QUOTA_RESET_TZ)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.timestamp()


def classify(exc: Exception) -> tuple[float, str]:
    """(parked_until, reason) for a failed call.

    Message-sniffing rather than typed fields because the SDK surfaces quota
    scope only in the human-readable body: 'PerDay' vs 'PerMinute'.
    """
    text = str(exc)
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)

    is_429 = code == 429 or "429" in text or "RESOURCE_EXHAUSTED" in text
    if is_429:
        lowered = text.lower()
        # Default a 429 with no scope hint to the DAILY park. Guessing
        # "per-minute" on a daily exhaustion reproduces the exact thrash this
        # class exists to prevent; guessing "daily" on a per-minute limit
        # costs one key for a few hours and the other two still serve.
        if "perminute" in lowered or "per minute" in lowered:
            return time.time() + _SHORT_PARK_S, "per-minute rate limit"
        return _next_quota_reset(), "daily quota exhausted"

    if code in (400, 401, 403) or "api key not valid" in text.lower():
        return _PERMANENT, "invalid or unauthorised key"

    # 5xx, timeouts, connection resets — transient, worth a short park.
    return time.time() + _SHORT_PARK_S, f"transient ({code or type(exc).__name__})"


class KeyPool:
    """Slot-ordered key rotation. Thread-safe: STT runs on the turn worker
    thread while the planner runs on the event loop, and both draw here."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._keys: dict[int, str] = {
            1: (settings.gemini_api_key or "").strip(),
            2: (settings.gemini_api_key_2 or "").strip(),
            3: (settings.gemini_api_key_3 or "").strip(),
        }
        self._parked: dict[int, float] = {}
        self._reasons: dict[int, str] = {}

    def _configured(self, slot: int) -> bool:
        # >10 chars mirrors the original's sanity check and rejects the
        # "your_key_here" placeholder people leave in .env.
        key = self._keys.get(slot, "")
        return len(key) > 10 and not key.startswith("your_key")

    def acquire(self) -> tuple[int, str] | None:
        """Lowest-numbered configured slot not currently parked, or None."""
        with self._lock:
            now = time.time()
            for slot in (1, 2, 3):
                if not self._configured(slot):
                    continue
                until = self._parked.get(slot)
                if until is not None:
                    if until > now:
                        continue
                    del self._parked[slot]
                    self._reasons.pop(slot, None)
                return slot, self._keys[slot]
            return None

    def report_success(self, slot: int) -> None:
        with self._lock:
            if self._parked.pop(slot, None) is not None:
                self._reasons.pop(slot, None)
                log.info("Gemini key %d recovered", slot)

    def report_failure(self, slot: int, exc: Exception) -> None:
        until, reason = classify(exc)
        with self._lock:
            self._parked[slot] = until
            self._reasons[slot] = reason
            remaining = "permanently" if until == _PERMANENT else f"{until - time.time():.0f}s"
            log.warning("Gemini key %d parked %s: %s", slot, remaining, reason)
            if all(
                not self._configured(s) or self._parked.get(s, 0) > time.time()
                for s in (1, 2, 3)
            ):
                log.error("All Gemini keys parked — voice will fail until one frees")

    def status(self) -> list[KeyStatus]:
        with self._lock:
            return [
                KeyStatus(
                    slot=slot,
                    configured=self._configured(slot),
                    parked_until=self._parked.get(slot),
                    reason=self._reasons.get(slot, ""),
                )
                for slot in (1, 2, 3)
            ]


pool = KeyPool()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_key_pool.py -v`
Expected: 10 passed.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 1035 passed, 3 deselected (1025 + 10 new).

- [ ] **Step 7: Commit**

```bash
git add backend/ai_modules/llm/key_pool.py tests/test_key_pool.py backend/server/config.py
git commit -F - <<'EOF'
feat(llm): three-key Gemini pool that parks exhausted keys until reset

Ported from the SG-CUBE camera module's APIKeyManager with its two
defects fixed.

That version parks ANY failed key for 60 seconds. Free-tier Gemini is
metered per DAY, so a key that spent its quota returns after a minute
and fails again, forever — and once all three exhaust, every turn pays
three dead network calls before giving up, re-tried every minute.
classify() now separates daily quota (park to next reset) from
per-minute rate limits and 5xx (60s) from an invalid key (permanent).

A 429 with no scope hint defaults to the DAILY park: guessing
"per-minute" on a daily exhaustion reproduces exactly the thrash this
class exists to prevent, while guessing "daily" on a per-minute limit
costs one key for a few hours and the other two still serve.

Quota reset is computed at a fixed UTC-8 rather than via ZoneInfo —
this machine has no tz database and tzdata is not installed, so
ZoneInfo('America/Los_Angeles') raises. During PDT this over-parks by
an hour, which is harmless.

Also dropped from the original: base64 "obfuscation" of keys on disk
(encoding, not encryption), os.environ mutation from library code, and
test_connection() — which calls client.models.list_models(), a method
that does not exist in google-genai 2.10.0.
EOF
```

---

### Task 3: Route `GeminiBackend` through the pool

**Files:**
- Modify: `backend/ai_modules/llm/backends/gemini_backend.py:73-77` (constructor) and the `generate` retry loop at 111-135
- Create: `tests/test_gemini_backend_key_pool.py`

**Interfaces:**
- Consumes: `pool` from Task 2.
- Produces: `GeminiBackend._client_for_call() -> tuple[int, genai.Client] | None`. Task 4 does NOT use this — `stt_gemini` builds its own client from the same pool.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gemini_backend_key_pool.py`:

```python
"""GeminiBackend must draw keys from the shared pool.

Without this, the planner burning key 1 leaves STT to retry key 1 one second
later, fail, and rotate independently — the two consumers each rediscover the
same dead key.
"""
import pytest
from google.genai import errors as genai_errors

from backend.ai_modules.llm import key_pool as kp
from backend.ai_modules.llm.backends import gemini_backend as gb


@pytest.fixture(autouse=True)
def three_keys(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "k" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_2", "j" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_3", "m" * 20)
    fresh = kp.KeyPool()
    monkeypatch.setattr(kp, "pool", fresh)
    monkeypatch.setattr(gb, "pool", fresh)
    return fresh


def test_backend_uses_pool_slot_one_first(three_keys):
    backend = gb.GeminiBackend()
    got = backend._client_for_call()
    assert got is not None
    slot, _client = got
    assert slot == 1


def test_backend_falls_through_to_slot_two_when_one_is_parked(three_keys):
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, "RESOURCE_EXHAUSTED PerDay")
    err.code = 429
    three_keys.report_failure(1, err)

    backend = gb.GeminiBackend()
    slot, _client = backend._client_for_call()
    assert slot == 2


def test_backend_returns_none_when_all_keys_parked(three_keys):
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, "API key not valid")
    err.code = 400
    for slot in (1, 2, 3):
        three_keys.report_failure(slot, err)

    backend = gb.GeminiBackend()
    assert backend._client_for_call() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gemini_backend_key_pool.py -v`
Expected: FAIL — `AttributeError: 'GeminiBackend' object has no attribute '_client_for_call'`

- [ ] **Step 3: Implement**

Add the import near the other backend imports in `gemini_backend.py`:

```python
from backend.ai_modules.llm.key_pool import pool
```

Replace the constructor at lines 73-77:

```python
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.default_model = settings.gemini_model
```

with:

```python
    def __init__(self):
        self.default_model = settings.gemini_model
        # Clients are built per call from the shared pool rather than pinned
        # here. A client constructed once in __init__ holds slot 1's key for
        # the life of the process, so a key parked by STT is still used by the
        # planner and vice versa — the two consumers each rediscover the same
        # dead key independently.
        self._clients: dict[int, genai.Client] = {}

    def _client_for_call(self) -> tuple[int, genai.Client] | None:
        """(slot, client) for the highest-priority unparked key, or None."""
        got = pool.acquire()
        if got is None:
            return None
        slot, key = got
        client = self._clients.get(slot)
        if client is None:
            client = genai.Client(api_key=key)
            self._clients[slot] = client
        return slot, client
```

In the `generate` retry loop, replace the body of the `try` at line ~113 and the `except` handling so the pool learns the outcome. The loop currently reads `self.client`; change it to acquire per attempt:

```python
        max_retries = settings.llm_max_retries
        for attempt in range(1, max_retries + 1):
            got = self._client_for_call()
            if got is None:
                _emit_degraded("all keys parked", "gave_up")
                log.error("Gemini: every API key is parked; cannot generate")
                raise RuntimeError("all Gemini API keys are parked")
            slot, client = got
            try:
                # `client.aio.models` is the async surface in google-genai.
                # This used to call `client.models.generate_content_async`,
                # which is the OLD google-generativeai SDK's name and does not
                # exist here — every call raised AttributeError, which
                # _is_gemini_retryable classes as non-retryable, so the turn
                # died outright. The unit tests only covered the retry helpers,
                # never this call, so it stayed green while dead.
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    ),
                    timeout=timeout,
                )
                pool.report_success(slot)
                return resp.text.strip()
            except Exception as e:
                pool.report_failure(slot, e)
                retryable, reason = _is_gemini_retryable(e)
                if not retryable or attempt >= max_retries:
                    if retryable:
                        _emit_degraded(reason, "gave_up")
                    log.exception("Gemini generate failed (attempt %d/%d, reason=%s)",
                                  attempt, max_retries, reason)
```

Leave the remainder of the existing `except` block (the backoff sleep and re-raise) exactly as it is.

**Note:** `self.client` may be referenced elsewhere in the file — the streaming method around line 208 and `active_model_name` at 218. Grep for `self.client` and convert every call site to `_client_for_call()` with matching `report_success`/`report_failure`. Do not leave a half-converted file.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gemini_backend_key_pool.py tests/test_llm_resilience.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 1038 passed, 3 deselected.

- [ ] **Step 6: Commit**

```bash
git add backend/ai_modules/llm/backends/gemini_backend.py tests/test_gemini_backend_key_pool.py
git commit -m "feat(llm): GeminiBackend draws keys from the shared pool

The client was constructed once in __init__ and pinned slot 1's key for
the life of the process. With STT about to become a second consumer of
the same quota, that means the planner keeps using a key STT has already
found dead, and each side rediscovers the exhaustion independently.

Clients are now built per slot, cached, and acquired per attempt, with
the outcome reported back so the pool's parking actually governs both
consumers."
```

---

### Task 4: `stt_gemini` — the drop-in replacement

**Files:**
- Create: `backend/ai_modules/speech/stt_gemini.py`
- Create: `tests/test_stt_gemini.py`

**Interfaces:**
- Consumes: `pool` from Task 2.
- Produces:
  - `transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict`
  - `transcribe(audio_path: str | Path) -> dict`
  - `encode_wav(audio: np.ndarray, sample_rate: int) -> bytes`
  - `SttUnavailable` exception with attribute `kind: str` in `{"no_network", "quota", "no_key"}`
  - Both transcribe functions return `{"text": str, "language": str, "language_probability": float, "duration_sec": float}` — byte-identical in shape to `stt_whisper`.
  - Task 5 imports the transcribe functions; Task 6 catches `SttUnavailable`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stt_gemini.py`:

```python
"""stt_gemini must be a true drop-in for stt_whisper.

trigger.py hands it float32 normalized to [-1, 1] (arr.astype(np.float32) /
32768.0) and reads result["text"]. voice.py hands it a file path. Anything
that changes those two contracts breaks the rule engine, the content gate,
and the archive — none of which are being modified.
"""
import wave
from io import BytesIO

import numpy as np
import pytest
from google.genai import errors as genai_errors

from backend.ai_modules.llm import key_pool as kp
from backend.ai_modules.speech import stt_gemini


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "k" * 20)
    monkeypatch.setattr(kp.settings, "gemini_api_key_2", "")
    monkeypatch.setattr(kp.settings, "gemini_api_key_3", "")
    fresh = kp.KeyPool()
    monkeypatch.setattr(stt_gemini, "pool", fresh)
    return fresh


class _FakeModels:
    def __init__(self, payload=None, raises=None):
        self._payload, self._raises = payload, raises
        self.last_contents = None
        self.last_config = None

    def generate_content(self, *, model, contents, config):
        if self._raises:
            raise self._raises
        self.last_contents, self.last_config = contents, config
        return type("R", (), {"text": self._payload})()


class _FakeClient:
    def __init__(self, payload=None, raises=None):
        self.models = _FakeModels(payload, raises)


def _tone(seconds=1.0, rate=16000) -> np.ndarray:
    """float32 in [-1, 1] — exactly what trigger.py passes."""
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_encode_wav_produces_16bit_mono_pcm():
    audio = _tone(0.5)
    blob = stt_gemini.encode_wav(audio, 16000)
    with wave.open(BytesIO(blob), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == len(audio)


def test_encode_wav_does_not_clip_full_scale_input():
    """float32 1.0 * 32768 overflows int16. Must clamp to 32767, not wrap
    to -32768 — a wrap turns the loudest sample into the quietest."""
    audio = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    blob = stt_gemini.encode_wav(audio, 16000)
    with wave.open(BytesIO(blob), "rb") as wf:
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    assert samples[0] == 32767
    assert samples[1] == -32768
    assert samples[2] == 0


def test_returns_whisper_result_shape(monkeypatch):
    client = _FakeClient('{"transcript": "open notepad", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    out = stt_gemini.transcribe_array(_tone(2.0), 16000)
    assert set(out) == {"text", "language", "language_probability", "duration_sec"}
    assert out["text"] == "open notepad"
    assert out["duration_sec"] == pytest.approx(2.0, abs=0.01)


def test_no_speech_detected_yields_empty_text(monkeypatch):
    """The existing content gate rejects '' — so no-speech must map to '',
    not to a plausible-sounding hallucination."""
    client = _FakeClient('{"transcript": "thank you", "speech_detected": false}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == ""


def test_transcript_is_stripped(monkeypatch):
    client = _FakeClient('{"transcript": "  lock the screen \\n", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == "lock the screen"


def test_unparseable_response_is_empty_not_an_exception(monkeypatch):
    """A malformed body must not become a command. Empty is the safe value —
    the content gate already rejects it."""
    client = _FakeClient("this is not json")
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    assert stt_gemini.transcribe_array(_tone(), 16000)["text"] == ""


def test_no_key_configured_raises_no_key(monkeypatch):
    monkeypatch.setattr(kp.settings, "gemini_api_key", "")
    monkeypatch.setattr(stt_gemini, "pool", kp.KeyPool())
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "no_key"


def test_quota_exhaustion_raises_quota_and_parks_the_key(monkeypatch, keys):
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, "RESOURCE_EXHAUSTED PerDay")
    err.code = 429
    monkeypatch.setattr(stt_gemini, "_client_for",
                        lambda: (1, _FakeClient(raises=err)))
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "quota"


def test_connection_error_raises_no_network(monkeypatch):
    monkeypatch.setattr(
        stt_gemini, "_client_for",
        lambda: (1, _FakeClient(raises=ConnectionError("getaddrinfo failed"))))
    with pytest.raises(stt_gemini.SttUnavailable) as exc:
        stt_gemini.transcribe_array(_tone(), 16000)
    assert exc.value.kind == "no_network"


def test_uses_a_real_sdk_method_name():
    """Both this repo and the camera module shipped calls to the OLD
    google-generativeai SDK and stayed green because the tests mocked the
    seam. df41d3a fixed generate_content_async; this guards the sync path."""
    from google.genai import models
    assert hasattr(models.Models, "generate_content")
    assert not hasattr(models.Models, "generate_content_async")


def test_transcribe_from_path_matches_array(monkeypatch, tmp_path):
    client = _FakeClient('{"transcript": "what time is it", "speech_detected": true}')
    monkeypatch.setattr(stt_gemini, "_client_for", lambda: (1, client))
    wav = tmp_path / "clip.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((_tone(1.0) * 32767).astype(np.int16).tobytes())
    assert stt_gemini.transcribe(wav)["text"] == "what time is it"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stt_gemini.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.ai_modules.speech.stt_gemini'`

- [ ] **Step 3: Implement `stt_gemini.py`**

```python
"""Speech-to-text via Gemini. Drop-in replacement for stt_whisper.

Deliberately exposes the SAME signatures stt_whisper does, so trigger.py and
voice.py change one import line each and the rule engine, the content gate,
the capture archive, and the five agents are untouched.

SYNCHRONOUS on purpose. Whisper's transcribe_array blocked, and trigger.py
calls it without await from inside _handle_wake_async — which itself runs on
the turn worker thread. Making this async would change the call shape at the
one site the whole design is trying not to disturb.

Structured output rather than a prose prompt. Whisper was steered with an
initial_prompt, and when the audio gave it nothing to work with it emitted
that prompt back as a transcript — fluent, confident, and dispatched to the
router as a command. A response_schema makes that failure structurally
impossible: the model fills a boolean and a string, and speech_detected=false
maps to "", which the existing content gate already rejects. This is why
is_prompt_echo() is not ported.
"""
from __future__ import annotations

import json
import logging
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
from google import genai
from google.genai import types

from backend.ai_modules.llm.key_pool import pool
from backend.server.config import settings

log = logging.getLogger(__name__)


class SttUnavailable(RuntimeError):
    """STT could not run at all. `kind` decides what the assistant says.

    Distinct kinds because they must not sound alike. The interrupt bug fixed
    in 59eb62f was exactly this failure: two different situations produced one
    message, so a user who had interrupted was told they had been misheard.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


# Biases recognition toward the command vocabulary — the legitimate version of
# what Whisper's initial_prompt was doing. Safe here in a way it was not there:
# the model answers into a schema, so this text has no field to leak into.
_SYSTEM_INSTRUCTION = (
    "You are a speech-to-text engine for a desktop voice assistant named Onyx. "
    "Transcribe the user's spoken command verbatim in English. "
    "Do not translate, answer, summarise, explain, or add punctuation the "
    "speaker did not imply. Return only what was said.\n"
    "Likely vocabulary: onyx, open, close, notepad, chrome, firefox, vscode, "
    "spotify, whatsapp, discord, telegram, calculator, explorer, command "
    "prompt, lock the screen, volume, brightness, stop, cancel, never mind, "
    "what time is it, weather, news, remind me, translate, summarize, "
    "read the screen, play on youtube, search.\n"
    "If the audio contains no intelligible speech — silence, noise, breathing, "
    "a cough — set speech_detected to false and transcript to an empty string. "
    "Never guess at words that are not there."
)

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING"},
        "speech_detected": {"type": "BOOLEAN"},
    },
    "required": ["transcript", "speech_detected"],
}

_EMPTY: dict = {
    "text": "",
    "language": "en",
    "language_probability": 1.0,
    "duration_sec": 0.0,
}

_clients: dict[int, genai.Client] = {}


def _client_for() -> tuple[int, genai.Client]:
    """(slot, client) from the shared pool. Raises SttUnavailable if none."""
    got = pool.acquire()
    if got is None:
        statuses = pool.status()
        if not any(s.configured for s in statuses):
            raise SttUnavailable("no_key", "no Gemini API key is configured")
        raise SttUnavailable(
            "quota", "every Gemini API key is parked (quota or auth)")
    slot, key = got
    client = _clients.get(slot)
    if client is None:
        client = genai.Client(api_key=key)
        _clients[slot] = client
    return slot, client


def encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 in [-1, 1] (what trigger.py passes) -> 16-bit mono PCM WAV.

    Clamps before casting. float32 1.0 * 32768 is 32768, which overflows int16
    and WRAPS to -32768 — turning the single loudest sample of a clip into the
    single quietest. numpy does that silently.
    """
    arr = np.asarray(audio)
    if arr.dtype != np.int16:
        arr = np.clip(arr.astype(np.float32) * 32768.0, -32768, 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())
    return buf.getvalue()


def _classify_transport(exc: Exception) -> str:
    """Which SttUnavailable.kind a failed call maps to."""
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429 or "resource_exhausted" in text or "429" in text:
        return "quota"
    if code in (400, 401, 403) or "api key not valid" in text:
        return "no_key"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return "no_network"
    for needle in ("getaddrinfo", "name resolution", "connection", "unreachable",
                   "timed out", "timeout", "ssl"):
        if needle in text:
            return "no_network"
    return "no_network"


def _parse(raw: str | None) -> str:
    """Schema payload -> transcript. Anything unparseable becomes "".

    Empty is the safe value: the content gate already rejects it, whereas a
    half-parsed body could reach the router as a command.
    """
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("stt_gemini: unparseable response body %r", raw[:200])
        return ""
    if not isinstance(data, dict) or not data.get("speech_detected"):
        return ""
    transcript = data.get("transcript")
    return transcript.strip() if isinstance(transcript, str) else ""


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Transcribe a captured command. Same contract as stt_whisper's."""
    arr = np.asarray(audio)
    if arr.size == 0:
        return dict(_EMPTY)
    duration = round(len(arr) / float(sample_rate), 3)

    slot, client = _client_for()
    wav_bytes = encode_wav(arr, sample_rate)
    try:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            ],
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                temperature=0.0,
            ),
        )
    except Exception as e:
        pool.report_failure(slot, e)
        kind = _classify_transport(e)
        log.warning("stt_gemini: %s on key %d: %s", kind, slot, e)
        raise SttUnavailable(kind, str(e)) from e

    pool.report_success(slot)
    return {
        "text": _parse(getattr(resp, "text", None)),
        "language": "en",
        "language_probability": 1.0,
        "duration_sec": duration,
    }


def transcribe(audio_path: str | Path) -> dict:
    """Transcribe a WAV file. Same contract as stt_whisper's."""
    with wave.open(str(audio_path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return transcribe_array(arr, rate)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stt_gemini.py -v`
Expected: 11 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 1049 passed, 3 deselected.

- [ ] **Step 6: Commit**

```bash
git add backend/ai_modules/speech/stt_gemini.py tests/test_stt_gemini.py
git commit -m "feat(stt): Gemini speech-to-text as a drop-in for stt_whisper

Same signatures, same result dict, synchronous like the function it
replaces — so trigger.py and voice.py will change one import line each
and the rule engine, content gate, capture archive and five agents stay
untouched.

Structured output instead of a prose prompt. Whisper was steered with
an initial_prompt and, when the audio gave it nothing, emitted that
prompt back as a transcript — fluent, confident, and dispatched to the
router as a command. A response_schema makes that impossible, so
is_prompt_echo() is not ported.

encode_wav clamps before casting: float32 1.0 * 32768 overflows int16
and wraps to -32768, silently turning a clip's loudest sample into its
quietest.

Not wired to anything yet."
```

---

### Task 5: Wire it in, behind a reversible setting

**Files:**
- Modify: `backend/server/config.py` (add `stt_backend`)
- Create: `backend/ai_modules/speech/stt.py`
- Modify: `backend/daemon/trigger.py:14`
- Modify: `backend/server/routes/voice.py:9`
- Create: `tests/test_stt_selector.py`

**Interfaces:**
- Consumes: `stt_gemini` (Task 4), existing `stt_whisper`.
- Produces: `backend.ai_modules.speech.stt.transcribe_array(...)`, `.transcribe(...)`, `.active_backend() -> str`. These are what `trigger.py` and `voice.py` import from Task 5 onward.

- [ ] **Step 1: Add the setting**

In `backend/server/config.py`, immediately after the `gemini_model` line added in Task 2:

```python
    # Which speech-to-text engine the voice path uses. "gemini" is the
    # intended end state; "whisper" is kept until the live gate in
    # docs/superpowers/specs/2026-08-25-gemini-stt-consolidation-design.md
    # section 7.1 passes, so a bad result is one config flip to revert
    # rather than a revert commit mid-session.
    stt_backend: str = "gemini"  # "gemini" | "whisper"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_stt_selector.py`:

```python
"""The selector is the revert switch. It must actually switch."""
import numpy as np
import pytest

from backend.ai_modules.speech import stt


def test_defaults_to_gemini(monkeypatch):
    monkeypatch.setattr(stt.settings, "stt_backend", "gemini")
    assert stt.active_backend() == "gemini"


def test_whisper_selectable(monkeypatch):
    monkeypatch.setattr(stt.settings, "stt_backend", "whisper")
    assert stt.active_backend() == "whisper"


def test_unknown_value_falls_back_to_gemini_and_warns(monkeypatch, caplog):
    monkeypatch.setattr(stt.settings, "stt_backend", "wisper")
    with caplog.at_level("WARNING"):
        assert stt.active_backend() == "gemini"
    assert "wisper" in caplog.text


def test_transcribe_array_dispatches_to_selected_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(stt.settings, "stt_backend", "whisper")
    monkeypatch.setattr(
        stt.stt_whisper, "transcribe_array",
        lambda a, sr=16000: calls.append("whisper") or {"text": "w"})
    monkeypatch.setattr(
        stt.stt_gemini, "transcribe_array",
        lambda a, sr=16000: calls.append("gemini") or {"text": "g"})

    out = stt.transcribe_array(np.zeros(16000, dtype=np.float32), 16000)
    assert calls == ["whisper"]
    assert out["text"] == "w"


def test_gemini_selected_dispatches_to_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(stt.settings, "stt_backend", "gemini")
    monkeypatch.setattr(
        stt.stt_whisper, "transcribe_array",
        lambda a, sr=16000: calls.append("whisper") or {"text": "w"})
    monkeypatch.setattr(
        stt.stt_gemini, "transcribe_array",
        lambda a, sr=16000: calls.append("gemini") or {"text": "g"})

    out = stt.transcribe_array(np.zeros(16000, dtype=np.float32), 16000)
    assert calls == ["gemini"]
    assert out["text"] == "g"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stt_selector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.ai_modules.speech.stt'`

- [ ] **Step 4: Implement the selector**

Create `backend/ai_modules/speech/stt.py`:

```python
"""Which STT engine the voice path uses.

Exists so the Gemini migration is one config flip to revert rather than a
revert commit mid-session. Deleted along with stt_whisper once the live gate
in the design doc's section 7.1 passes — it is scaffolding, not architecture.

Imports both modules eagerly. stt_whisper's import is cheap (the model loads
lazily inside get_model, not at import), so there is no reason to defer it
and every reason not to: a lazy import that fails does so mid-turn.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from backend.ai_modules.speech import stt_gemini, stt_whisper
from backend.server.config import settings

log = logging.getLogger(__name__)

_VALID = ("gemini", "whisper")


def active_backend() -> str:
    choice = (settings.stt_backend or "gemini").strip().lower()
    if choice not in _VALID:
        log.warning("unknown STT_BACKEND %r; using gemini", settings.stt_backend)
        return "gemini"
    return choice


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    if active_backend() == "whisper":
        return stt_whisper.transcribe_array(audio, sample_rate)
    return stt_gemini.transcribe_array(audio, sample_rate)


def transcribe(audio_path: str | Path) -> dict:
    if active_backend() == "whisper":
        return stt_whisper.transcribe(audio_path)
    return stt_gemini.transcribe(audio_path)
```

- [ ] **Step 5: Repoint `trigger.py`**

Replace line 14:

```python
from backend.ai_modules.speech.stt_whisper import transcribe_array, transcribe_stream
```

with:

```python
from backend.ai_modules.speech.stt import transcribe_array
```

`transcribe_stream` is imported here and never called — line 655 calls `transcribe_array`. Dropping it from the import is safe and is verified by the full suite in Step 7.

Also fix the docstring at line ~624 that claims `transcribe_stream` is used:

```python
    Phase C1: Uses `transcribe_stream` for streaming STT with partial results.
```

becomes:

```python
    Transcribes the whole captured utterance in one call via
    backend.ai_modules.speech.stt. The old comment here claimed
    `transcribe_stream` was used for partial results; it never was — that
    function had no caller anywhere in the tree.
```

And update the log line at ~644, which names the engine that is no longer necessarily running:

```python
            print(f"[trigger] skipping whisper: capture too quiet (rms={rms:.0f})")
```

becomes:

```python
            print(f"[trigger] skipping STT: capture too quiet (rms={rms:.0f})")
```

- [ ] **Step 6: Repoint `voice.py`**

Replace line 9:

```python
from backend.ai_modules.speech.stt_whisper import transcribe
```

with:

```python
from backend.ai_modules.speech.stt import transcribe
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 1054 passed, 3 deselected.

If tests fail because they patch `backend.ai_modules.speech.stt_whisper.transcribe_array` and production now calls it through `stt`, re-point the patch target at `backend.ai_modules.speech.stt.transcribe_array`. Do NOT weaken an assertion to make it pass — a test that patched the old seam was testing a real path and still needs to.

These four are the likely ones, and every one of them is asserting behaviour that must still hold after the swap. **Re-point them; do not delete them:**

- `tests/test_lazy_init_races.py` — concurrent first-use of the STT path
- `tests/test_wake_preroll.py` — the pre-roll audio reaching the transcriber
- `tests/test_transcript_gate.py` — the content gate that rejects empty text
- `tests/test_hallucination_compound.py` — junk transcripts not becoming commands

`test_hallucination_compound.py` deserves a second look rather than a mechanical re-point: it guards against a fabricated transcript being dispatched, which is exactly the failure `stt_gemini`'s `speech_detected` boolean is supposed to make structural. Confirm it still exercises something real against the new backend. If it does not, say so in the commit rather than quietly deleting it.

Run this to find every test that reaches for the old seam, rather than discovering them one failure at a time:

```bash
grep -rln "stt_whisper\|transcribe_array\|transcribe_stream" tests/
```

- [ ] **Step 8: Commit**

```bash
git add backend/ai_modules/speech/stt.py backend/server/config.py backend/daemon/trigger.py backend/server/routes/voice.py tests/test_stt_selector.py
git commit -F - <<'EOF'
feat(stt): route the voice path through a selectable STT backend

STT_BACKEND=gemini by default, whisper still selectable. The switch
exists so a bad live result is one config flip to revert rather than a
revert commit mid-session; it gets deleted with stt_whisper once the
gate in the design doc's 7.1 passes.

Also drops the transcribe_stream import from trigger.py and corrects
the docstring above _handle_wake_async, which advertised "Uses
transcribe_stream for streaming STT with partial results". It never
did — line 655 calls transcribe_array and transcribe_stream had no
caller anywhere in the tree.

The "skipping whisper" log line now says "skipping STT", since which
engine runs is a setting.
EOF
```

---

### Task 6: Make the failure branches speak

**Files:**
- Modify: `backend/daemon/trigger.py` (the `try` around the transcribe call, ~line 653-657)
- Create: `tests/test_stt_unavailable_speaks.py`

**Interfaces:**
- Consumes: `SttUnavailable` from Task 4.
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stt_unavailable_speaks.py`:

```python
"""When STT cannot run, say so — differently per cause — and reach IDLE.

Silence is not acceptable and neither is one generic line. 59eb62f fixed
exactly this shape of bug: being interrupted and being misheard produced the
same sentence, so the user was told they had been misheard when they had not.
Piper is local and still works in every case here.
"""
import numpy as np
import pytest

from backend.ai_modules.speech.stt_gemini import SttUnavailable
from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import trigger


@pytest.fixture
def spoken(monkeypatch):
    said = []
    monkeypatch.setattr(trigger, "speak", lambda text, *a, **k: said.append(text))
    monkeypatch.setattr(trigger, "_play_chime", lambda: None)
    return said


def _raise(kind):
    def _f(audio, sample_rate=16000):
        raise SttUnavailable(kind, f"simulated {kind}")
    return _f


@pytest.mark.parametrize("kind,needle", [
    ("no_network", "network"),
    ("quota", "limit"),
    ("no_key", "key"),
])
def test_each_cause_speaks_its_own_line(monkeypatch, spoken, kind, needle):
    monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
    audio = (np.ones(16000, dtype=np.int16) * 4000).tobytes()

    trigger.handle_wake(audio)

    assert spoken, f"{kind} said nothing at all"
    assert needle in spoken[0].lower(), f"{kind} said {spoken[0]!r}"


def test_the_three_lines_are_distinct(monkeypatch):
    """If two causes share a sentence, the user cannot tell them apart —
    which is the bug 59eb62f fixed, reintroduced."""
    lines = set()
    for kind in ("no_network", "quota", "no_key"):
        said = []
        monkeypatch.setattr(trigger, "speak", lambda t, *a, **k: said.append(t))
        monkeypatch.setattr(trigger, "_play_chime", lambda: None)
        monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
        trigger.handle_wake((np.ones(16000, dtype=np.int16) * 4000).tobytes())
        lines.add(said[0])
    assert len(lines) == 3, f"causes share wording: {lines}"


@pytest.mark.parametrize("kind", ["no_network", "quota", "no_key"])
def test_state_returns_to_idle(monkeypatch, spoken, kind):
    """A turn that dies without transitioning leaves the listener stuck in
    SPEAKING, which then makes the wake word need barge-in loudness to fire."""
    monkeypatch.setattr(trigger, "transcribe_array", _raise(kind))
    trigger.handle_wake((np.ones(16000, dtype=np.int16) * 4000).tobytes())
    assert state_manager.current == AssistantState.IDLE
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stt_unavailable_speaks.py -v`
Expected: FAIL — `SttUnavailable` propagates out of `handle_wake` uncaught.

- [ ] **Step 3: Implement**

Add the import to `trigger.py` next to the STT import:

```python
from backend.ai_modules.speech.stt_gemini import SttUnavailable
```

Add the message table near the other module constants (below `SAMPLE_RATE`):

```python
# What Onyx says when speech-to-text cannot run at all. Three distinct lines,
# because they are three distinct situations and a user who cannot tell them
# apart cannot act on them: one is "check your wifi", one is "wait until
# tomorrow", one is "fix your .env". Sharing wording here would reintroduce
# the confusion 59eb62f fixed between being interrupted and being misheard.
_STT_UNAVAILABLE_SPEECH = {
    "no_network": "I can't reach the network right now.",
    "quota": "I've hit my daily limit — it resets tonight.",
    "no_key": "My API key isn't set up.",
}
```

Wrap the transcribe call at ~line 653. The existing code is:

```python
        try:
            # Use streaming STT - audio_float is already the full captured audio
            # For true streaming, we'd need to refactor wake_word to yield chunks
            stt = transcribe_array(audio_float, SAMPLE_RATE)
            turn.mark("stt_done")
```

Replace with:

```python
        try:
            try:
                stt = transcribe_array(audio_float, SAMPLE_RATE)
            except SttUnavailable as e:
                # Speak, then end the turn. Piper is local, so this is the one
                # part of the pipeline that still works with no network.
                line = _STT_UNAVAILABLE_SPEECH.get(
                    e.kind, "Something went wrong with speech recognition.")
                print(f"[trigger] STT unavailable ({e.kind}): {e}")
                log.warning("STT unavailable (%s): %s", e.kind, e)
                try:
                    speak(line)
                except Exception:
                    log.exception("could not speak the STT failure notice")
                state_manager.transition_to(AssistantState.IDLE)
                latency_ledger().record(turn)
                return False
            turn.mark("stt_done")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stt_unavailable_speaks.py -v`
Expected: 7 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 1061 passed, 3 deselected.

- [ ] **Step 6: Commit**

```bash
git add backend/daemon/trigger.py tests/test_stt_unavailable_speaks.py
git commit -F - <<'EOF'
feat(voice): say why speech recognition failed, in three distinct ways

Cloud STT introduces failures Whisper never had: no network, daily
quota spent, key not configured. Silence would leave the user wondering
whether Onyx heard them, and one generic line would leave them unable
to act — those three need "check your wifi", "wait until tomorrow" and
"fix your .env" respectively.

A test asserts the three sentences are distinct. Sharing wording is the
bug 59eb62f fixed between being interrupted and being misheard, which
is what happens when two different situations sound the same.

Every branch transitions to IDLE. A turn that dies without transitioning
leaves the listener in SPEAKING, which then makes the wake word require
barge-in loudness to fire at all.

Piper is local, so the notice is audible even with no network.
EOF
```

---

### Task 7: The gate — real voice, real hardware

This task runs software; it does not write much. **Do not proceed to Task 8 on a FAIL.**

> **Instruction to whoever executes this task, from the owner:**
>
> **Do not optimise the results to justify Gemini. Record what actually happens.**
> If Gemini fails the gate, stop here and leave the rollback intact
> (`STT_BACKEND=whisper`, Whisper undeleted).
>
> The purpose of this gate is not to prove the migration right. It is to give
> permission to delete Whisper *only if* the evidence says that is safe. A
> re-run that happened to look better is not a result; report the distribution
> across all runs, including the bad one. Do not drop an outlier without saying
> you dropped it and why.

**Three independent gates. All three must pass — they do not trade against each other.** A latency win does not buy a recognition failure, and nothing buys a safety failure.

| Gate | Requirement |
|---|---|
| **Latency** | Materially better than the Task 1 Whisper distribution, at the threshold the owner set in Task 1 Step 4. Compared on median AND p95 — a good median with a bad tail is a fail. |
| **Recognition** | Real spoken commands reliably produce the intended transcript and fire the intended rule. |
| **Safety / state** | Zero incorrect rule executions. Every failure path returns to IDLE. |

**Files:**
- Create: `tools/_scratch/stt_gate.py` (git-ignored)
- Modify: `logs.md`

**Interfaces:**
- Consumes: Task 1's baseline numbers; everything from Tasks 2-6.
- Produces: a PASS/FAIL verdict recorded in `logs.md`. Task 8 is gated on it.

- [ ] **Step 1: Build the corpus half of the gate**

Copy `tools/_scratch/stt_baseline.py` to `tools/_scratch/stt_gate.py` and change its single import from `stt_whisper` to `stt`, so the same scoring runs against whichever backend `STT_BACKEND` selects. Everything else — `intent_of`, `load_float32`, the verdict logic — stays byte-identical, so the two runs are genuinely comparable.

- [ ] **Step 2: Run the corpus half**

Run: `.venv/Scripts/python.exe tools/_scratch/stt_gate.py`

Records gate rows 1, 2 and 3. **Row 2 is absolute: any `WRONG-RULE` is a FAIL regardless of every other number.** The Vosk probe showed how quietly a wrong-rule fire ships — `translate → lang="him the"` was consistent across every take and looked unremarkable in aggregate.

- [ ] **Step 3: Run the live half**

These cannot be automated and must be done by hand, speaking to the running assistant:

| Row | How to run it |
|---|---|
| 4 | ≥10 real spoken commands; read `wake`→`first_audio_out` from `/diagnostics/latency` |
| 5 | Disconnect wifi, say "onyx open notepad", confirm the network line and IDLE |
| 6 | Set all three keys to a spent or bogus value, confirm the limit line (different from row 5) and IDLE |
| 7 | Set key 1 bogus and keys 2-3 valid; confirm a turn completes, then check `pool.status()` shows slot 1 parked |
| 8 | Over ≥20 real turns, count requests actually consumed; compare against 1 per rule-hit and 2 per planner command |
| 9 | After every one of rows 5-8, confirm `/diagnostics` shows IDLE |
| 10 | Speak over Onyx mid-reply; confirm barge-in still cuts it and the turn ends without the "could you say it again" line |

- [ ] **Step 4: Record the verdict**

Append a `## Phase 4 — GATE RESULT` section to `logs.md` with every row, its measured value, the Task 1 baseline beside it, and PASS or FAIL. **A row that could not be measured is recorded as FAIL, not omitted.**

- [ ] **Step 5: Report to the owner and get an explicit go/no-go**

Present the table. On any FAIL, stop: fix the Gemini path and re-run the whole gate. Do not proceed to Task 8 and do not argue a threshold down after seeing the number — that is what Task 1 Step 4 fixed the tolerance in advance to prevent.

---

### Task 8: Delete — only on a PASS

**Precondition: Task 7 recorded PASS on all ten rows and the owner said go.** If not, stop.

**Files:**
- Delete: `backend/ai_modules/speech/stt_whisper.py`, `backend/ai_modules/speech/stt_manager.py`, `backend/ai_modules/speech/stt.py`, `backend/ai_modules/speech/livekit_worker.py`, `tests/test_stt_manager.py`, `tests/test_prompt_echo_guard.py`, `tests/test_stt_selector.py`
- Modify: `backend/daemon/trigger.py`, `backend/server/routes/voice.py`, `backend/server/config.py`, `requirements.txt`, `tests/test_ocr_reader.py`

- [ ] **Step 1: Repoint the two call sites straight at `stt_gemini`**

In `trigger.py` and `voice.py`, change `from backend.ai_modules.speech.stt import ...` to `from backend.ai_modules.speech.stt_gemini import ...`. The selector was scaffolding for the gate and has no reason to survive it.

- [ ] **Step 2: Give `test_ocr_reader.py` its own fixture**

`tests/test_ocr_reader.py:77` reaches into `ultralytics`' site-packages for a sample JPEG. That is the only thing in the repo keeping a multi-gigabyte dependency (and `torch`) installed. Replace with a generated image so nothing is checked in:

```python
    # Was: a JPEG borrowed from ultralytics' site-packages assets. That was
    # the entire reason a multi-GB vision dependency (and torch with it) was
    # installed. The OCR path needs an image with legible text, not that
    # specific photograph.
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 200), "white")
    ImageDraw.Draw(img).text((20, 80), "HELLO ONYX", fill="black")
    pt = tmp_path / "ocr_fixture.png"
    img.save(pt)
```

Add `tmp_path` to the test's parameters. Read the surrounding test first — if it asserts on content specific to the old photo, update the assertion to match the new text.

- [ ] **Step 3: Delete the files**

```bash
git rm backend/ai_modules/speech/stt_whisper.py \
       backend/ai_modules/speech/stt_manager.py \
       backend/ai_modules/speech/stt.py \
       backend/ai_modules/speech/livekit_worker.py \
       tests/test_stt_manager.py \
       tests/test_prompt_echo_guard.py \
       tests/test_stt_selector.py
```

`test_prompt_echo_guard.py` goes because the bug it guards is structurally impossible under a response schema — there is no field for prose to leak into. `test_stt_manager.py` tests profile selection, CUDA registration and idle unloading, none of which exist any more.

- [ ] **Step 4: Strip the dead settings**

From `backend/server/config.py` remove: `stt_backend`, `whisper_model`, `whisper_model_gpu`, `whisper_model_cpu`, `stt_profile`, `stt_idle_unload_s`, `voice_pipeline`, `livekit_url`, `livekit_api_key`, `livekit_api_secret`.

Grep each name across `backend/`, `tests/` and `tools/` before removing it. `voice_pipeline` in particular is read by `livekit_worker.py:23` (being deleted) and referenced in `tests/test_all_phases.py` — fix that reference rather than deleting the test.

- [ ] **Step 5: Strip the dependencies**

From `requirements.txt` remove `faster-whisper==1.1.0`, `silero-vad>=4.0.0`, `ultralytics==8.4.115`, and the commented livekit block. Leave `vosk==0.3.45` and `piper-tts==1.4.2` — both still in use.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: green. The count drops by however many tests the deleted files held; note the new number.

- [ ] **Step 7: Verify nothing still reaches for what is gone**

```bash
grep -rn "stt_whisper\|stt_manager\|faster_whisper\|silero\|transcribe_stream\|livekit\|ultralytics" --include="*.py" backend/ tests/ tools/
```

Expected: no hits outside comments. Any hit is an unfinished deletion.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor: remove Whisper, and the dead weight it was hiding

Gemini STT passed the live gate in the design doc's section 7.1, so the
fallback comes out.

Deleted:
  stt_whisper.py       245 ln
  stt_manager.py       233 ln  profiles, CUDA PATH hack, battery policy
  stt.py                       gate-only selector, scaffolding by design
  livekit_worker.py     81 ln  unreachable: voice_pipeline defaults to
                               "local", nothing overrides it, and the
                               livekit package was never installed
  faster-whisper, silero-vad, ultralytics, nvidia CUDA wheels

The silero-vad path was already dead before this change: trigger.py
imported transcribe_stream, its docstring advertised it, and line 655
called transcribe_array instead. It had no caller anywhere.

ultralytics was referenced by no backend module at all. Its only
consumer in the repo was test_ocr_reader.py borrowing a sample JPEG
from its site-packages — a multi-GB dependency, and the reason torch
was installed, kept alive for one test image. That test now draws its
own.

Offline voice is gone with this commit. Measured, not assumed: Vosk
serves 4/30 rules on the small model and 3/30 on the larger one, and
"stop" decodes as 'top' on every take of both. There is no local ASR
on this machine that can drive the rule engine.
EOF
```

---

## Not in this plan

**The `core/tools/` audit** (spec §7 phase 7) is a separate project: 6,246 lines across 44 modules, sharing no code with the STT work. It needs its own plan. Note before starting it that `dogfooding.json` holds only `tools_total`/`tools_success` aggregates — there is no per-tool usage data — so a static reachability audit finds dead code but cannot find unused-but-live code, and every removal needs owner approval.

**The merged audio→plan single call** (one Gemini request per turn instead of two) stays out until the gate produces real latency and request-count numbers. It halves per-turn quota cost but restructures Commander, which this plan is built specifically to avoid touching.
