from functools import lru_cache

from supabase import Client, create_client

from backend.server.config import settings


@lru_cache(maxsize=1)
def get_anon_client() -> Client:
    """Anon-key client. Respects RLS. Use for end-user-acting calls."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache(maxsize=1)
def get_service_client() -> Client:
    """Service-role client. BYPASSES RLS. Backend-only — never expose to clients."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
