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


def test_daily_quota_parks_until_the_reset_not_seconds(pool):
    """The whole point of this class. 60s would thrash.

    Asserts the park lands ON the next quota reset rather than merely
    exceeding some duration. The earlier `> 3600` form was clock-dependent:
    the reset is a fixed wall-clock instant (midnight UTC-8), so within the
    final hour before it the correct park is legitimately under an hour and
    the test failed on working code — daily, for an hour, around 12:30 IST.
    Anchoring to _next_quota_reset() still distinguishes the daily park from
    the 60s transient park, which is the behaviour actually under test.
    """
    pool.report_failure(1, _client_error(
        429, "RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
             "'generate_content_free_tier_requests' PerDay"))
    status = {s.slot: s for s in pool.status()}[1]
    assert status.parked_until is not None
    assert status.parked_until == pytest.approx(kp._next_quota_reset(), abs=2)
    assert pool.acquire() == (2, "j" * 20)


def test_ambiguous_429_defaults_to_daily_park(pool):
    """The headline defect in the ported original: it parked EVERY failure
    for 60s regardless of scope, so a key that had spent its daily quota
    came back off cooldown a minute later and failed again, forever.

    classify() defaults a 429 with neither 'PerDay' nor 'PerMinute' in the
    body to the daily park on purpose (guessing per-minute on a daily
    exhaustion reproduces exactly that thrash). Every other 429 test here
    passes an explicit scope hint; this is the one that pins the default
    itself, so a regression to "unscoped 429 -> 60s" cannot slip back in
    silently.
    """
    pool.report_failure(1, _client_error(
        429, "RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
             "'generate_content_free_tier_requests'"))
    status = {s.slot: s for s in pool.status()}[1]
    assert status.parked_until is not None
    # Anchored to the reset instant, not a duration — see the sibling daily
    # test for why `> 3600` was clock-dependent and failed on working code.
    assert status.parked_until == pytest.approx(kp._next_quota_reset(), abs=2)
    assert status.reason == "daily quota exhausted"


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
