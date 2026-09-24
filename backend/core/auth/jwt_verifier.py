# pyjwt ships with the optional 'supabase' extra, so it is imported inside
# the functions: this module loads at boot through auth/deps.py.
from fastapi import HTTPException, status

from backend.server.config import settings

_jwks_client = None


def _get_jwks_client():
    from jwt import PyJWKClient

    global _jwks_client
    if _jwks_client is None:
        if not settings.supabase_url:
            raise RuntimeError("SUPABASE_URL must be set in .env")
        _jwks_client = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwks_client


def verify_token(token: str) -> dict:
    """Verify a Supabase-issued JWT.

    Supabase uses asymmetric keys (ES256) for new projects — we fetch JWKS
    and verify with the matching public key. Falls back to HS256 with the
    shared secret for legacy projects.
    """
    import jwt

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError as e:
        if settings.supabase_jwt_secret:
            try:
                return jwt.decode(
                    token,
                    settings.supabase_jwt_secret,
                    algorithms=["HS256"],
                    audience="authenticated",
                )
            except jwt.InvalidTokenError as e2:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token: {e2}",
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWKS verification failed: {e}",
        )
