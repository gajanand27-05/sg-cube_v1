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
