"""Supabase is an optional extra. Without it the app must boot, the HUD must
work as the local user, and account routes must say why they are off (503)
rather than 500 on an ImportError."""
import pytest
from fastapi.testclient import TestClient

from backend.database import supabase_client


@pytest.fixture
def accounts_off(monkeypatch):
    monkeypatch.setattr(supabase_client, "installed", lambda: False)
    supabase_client.get_anon_client.cache_clear()
    supabase_client.get_service_client.cache_clear()
    yield
    supabase_client.get_anon_client.cache_clear()
    supabase_client.get_service_client.cache_clear()


@pytest.fixture
def client():
    from backend.server.main import app

    # A real loopback peer: TestClient otherwise reports "testclient", which
    # get_local_user (rightly) does not treat as localhost.
    return TestClient(app, client=("127.0.0.1", 50000))


def test_clients_refuse_with_a_503(accounts_off):
    with pytest.raises(supabase_client.SupabaseUnavailable) as e:
        supabase_client.get_service_client()
    assert e.value.status_code == 503
    assert "extra" in e.value.detail
    assert supabase_client.configured() is False


def test_login_answers_503_not_500(accounts_off, client):
    r = client.post("/auth/login", json={"email": "a@b.c", "password": "secret1"})
    assert r.status_code == 503, r.text


def test_bearer_token_answers_503_before_touching_pyjwt(accounts_off, client, monkeypatch):
    from backend.core.auth import jwt_verifier

    monkeypatch.setattr(jwt_verifier, "verify_token",
                        lambda t: pytest.fail("verify_token needs pyjwt from the extra"))
    r = client.get("/auth/whoami", headers={"Authorization": "Bearer x.y.z"})
    assert r.status_code == 503, r.text


def test_local_hud_user_still_works(accounts_off, client):
    r = client.get("/auth/whoami")
    assert r.status_code == 200
    assert r.json()["email"] == "local@sgcube.local"


def test_health_reports_accounts_off(accounts_off, client):
    assert client.get("/health").json()["supabase_configured"] is False


def test_turns_do_not_attempt_the_command_log(accounts_off, monkeypatch):
    from backend.core.orchestrator import router

    monkeypatch.setattr(router, "get_service_client",
                        lambda: pytest.fail("must not reach for Supabase when it is off"))
    router._log_to_db("u", "hello", None, "rule", "success", 1)
