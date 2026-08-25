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
