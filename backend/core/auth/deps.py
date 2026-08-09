import ipaddress
import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.auth.jwt_verifier import verify_token
from backend.database.supabase_client import get_service_client
from backend.server.config import settings

DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"


def _parse_host(host: str):
    """The one IP parser. None when `host` isn't an address at all."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_private_host(host: str) -> bool:
    """True for loopback / RFC1918 peers. The old startswith('172.') check
    also matched public 172.x space outside 172.16.0.0/12.

    Lives here rather than in routes/remote.py (its original home) because
    it's an access-control primitive; remote.py re-exports it for
    routes/phone_stream.py.
    """
    addr = _parse_host(host)
    return addr is not None and (addr.is_loopback or addr.is_private)


def _is_loopback_host(host: str) -> bool:
    addr = _parse_host(host)
    return addr is not None and addr.is_loopback


def peer_allowed(host: str | None) -> bool:
    """May this credential-less peer reach a desktop-sensitive route?

    The HUD sends no Authorization header (verified: nothing in frontend/src
    touches a token), so these routes can't require a JWT without breaking the
    dashboard. What they CAN require is that the peer is the same machine —
    the HUD runs on the host, the phone never touches these routes.

    Default: loopback only. `ALLOW_LAN_HUD=true` widens to RFC1918 for the
    user who opens the HUD via the machine's LAN IP (plausible, since the
    phone-camera feature needs APP_HOST=0.0.0.0) — an opt-in escape hatch, so
    the safe posture holds for anyone who never sets it.
    """
    # "testclient" is what FastAPI's TestClient reports; a real uvicorn peer is
    # always an IP, so this can't open anything in production.
    if host is None or host == "testclient":
        return True
    return _is_private_host(host) if settings.allow_lan_hud else _is_loopback_host(host)


def require_local_peer(request: Request) -> None:
    """FastAPI dependency form of peer_allowed(). Mounted router-wide on the
    routes that expose the desktop or its memory (screenshot, memory, system,
    agents, diagnostics). WebSockets can't raise HTTPException — they call
    peer_allowed() directly and close with 4403."""
    host = request.client.host if request.client else None
    if not peer_allowed(host):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is restricted to the local machine. "
                   "Set ALLOW_LAN_HUD=true to allow private-LAN peers.",
        )


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
