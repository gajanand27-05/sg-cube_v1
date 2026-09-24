"""Supabase is OPTIONAL: accounts, admin approval and the command_logs table.

A single-user laptop install has none of it — the HUD authenticates as the
local daemon user (auth/deps.get_local_user) and nothing in a turn needs the
cloud. The packages ship as an extra (`uv sync --extra supabase`), so nothing
here may import them at module level: this module is imported at boot through
the auth routes.
"""
from functools import lru_cache
import importlib.util

from fastapi import HTTPException, status

from backend.server.config import settings


class SupabaseUnavailable(HTTPException):
    """Accounts are not enabled on this install. A 503, so every route that
    reaches for a client answers with the reason instead of a bare 500."""

    def __init__(self, reason: str):
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail=f"Supabase accounts are not enabled: {reason}")


def installed() -> bool:
    return importlib.util.find_spec("supabase") is not None


def configured() -> bool:
    """Package present AND .env carries a project URL and a key."""
    return bool(installed() and settings.supabase_url
                and (settings.supabase_anon_key or settings.supabase_service_role_key))


def _create(key: str, key_name: str):
    if not installed():
        raise SupabaseUnavailable("the 'supabase' extra is not installed")
    if not settings.supabase_url or not key:
        raise SupabaseUnavailable(f"SUPABASE_URL and {key_name} must be set in .env")
    from supabase import create_client

    return create_client(settings.supabase_url, key)


@lru_cache(maxsize=1)
def get_anon_client():
    """Anon-key client. Respects RLS. Use for end-user-acting calls."""
    return _create(settings.supabase_anon_key, "SUPABASE_ANON_KEY")


@lru_cache(maxsize=1)
def get_service_client():
    """Service-role client. BYPASSES RLS. Backend-only — never expose to clients."""
    return _create(settings.supabase_service_role_key, "SUPABASE_SERVICE_ROLE_KEY")
