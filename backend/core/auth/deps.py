import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.auth.jwt_verifier import verify_token
from backend.database.supabase_client import get_service_client

DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"


def get_bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    return authorization.split(" ", 1)[1].strip()


def get_current_user(token: Annotated[str, Depends(get_bearer_token)]) -> dict:
    payload = verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing 'sub' claim"
        )

    sb = get_service_client()
    res = sb.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    return {"jwt": payload, "profile": res.data}


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    profile = user["profile"]
    if profile["role"] != "admin" or not profile["is_approved_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


def get_local_user(request: Request) -> dict:
    """Auto-authenticate as the daemon user for local requests.
    
    Used by the web UI in local mode — skips Supabase JWT verification
    when the request originates from localhost.
    """
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Local authentication only available from localhost",
        )
    return {
        "jwt": {},
        "profile": {
            "id": DAEMON_USER_ID,
            "email": "local@sgcube.local",
            "role": "user",
        },
    }


def get_any_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Try JWT auth first; fall back to localhost auto-auth for the web UI."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return get_current_user(token)
    return get_local_user(request)
