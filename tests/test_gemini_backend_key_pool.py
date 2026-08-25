"""GeminiBackend must draw keys from the shared pool.

Without this, the planner burning key 1 leaves STT to retry key 1 one second
later, fail, and rotate independently — the two consumers each rediscover the
same dead key.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as genai_errors

from backend.ai_modules.llm import key_pool as kp
from backend.ai_modules.llm.backends import gemini_backend as gb
from backend.server.config import settings


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


def test_generate_rotates_to_next_slot_after_retryable_failure(three_keys, monkeypatch):
    """The actual integration Task 3 exists for: generate() acquires slot 1,
    slot 1's client fails retryably, the pool parks slot 1, the NEXT attempt
    acquires slot 2, and that call succeeds. Covered elsewhere only as two
    disjoint halves — key_pool's own tests never call GeminiBackend, and
    test_llm_resilience's SDK-surface tests only ever exercise one slot. This
    drives generate()'s real retry loop through both slots with real
    (mocked) SDK call objects, and checks the pool ends up in the state the
    retry loop is supposed to leave it in.
    """
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_backoff_base_s", 0.0)

    # A 429 with no PerDay/PerMinute hint — retryable per _is_gemini_retryable,
    # and classify() parks it on the daily schedule (see test_key_pool.py's
    # test_ambiguous_429_defaults_to_daily_park for that half in isolation).
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, "429 RESOURCE_EXHAUSTED")
    err.code = 429

    slot1_client = MagicMock()
    slot1_client.aio.models.generate_content = AsyncMock(side_effect=err)

    slot2_resp = MagicMock()
    slot2_resp.text = " ok "
    slot2_client = MagicMock()
    slot2_client.aio.models.generate_content = AsyncMock(return_value=slot2_resp)

    def _fake_client_ctor(api_key=None, **_kw):
        if api_key == "k" * 20:  # slot 1
            return slot1_client
        if api_key == "j" * 20:  # slot 2
            return slot2_client
        raise AssertionError(f"unexpected api_key for this test: {api_key!r}")

    monkeypatch.setattr(gb.genai, "Client", _fake_client_ctor)

    backend = gb.GeminiBackend()
    result = asyncio.run(backend.generate("ping"))

    assert result == "ok"
    assert slot1_client.aio.models.generate_content.await_count == 1
    assert slot2_client.aio.models.generate_content.await_count == 1

    status = {s.slot: s for s in three_keys.status()}
    assert status[1].parked_until is not None and status[1].parked_until > time.time(), (
        "slot 1 must be parked after its retryable failure"
    )
    assert status[2].parked_until is None, "slot 2 succeeded and must not be parked"
