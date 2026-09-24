import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from backend.core.auth.deps import peer_allowed, require_local_peer
from backend.server import hud_confirm, session
from backend.server.config import settings
from backend.server.ws_ui import get_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["ui"])
session_router = APIRouter(tags=["ui"])


@session_router.get("/api/session", dependencies=[Depends(require_local_peer)])
def get_session(request: Request):
    """The HUD's WebSocket token. Readable only by this app's own pages: other
    origins get no CORS grant to read it, and the Host check rejects a DNS-
    rebound hostname (see backend/server/session.py)."""
    if not session.host_header_ok(request.headers.get("host"), settings.allow_lan_hud):
        raise HTTPException(status_code=403, detail="unexpected Host")
    if not session.origin_ok(request.headers.get("origin"), request.headers.get("host"),
                             settings.allow_lan_hud):
        raise HTTPException(status_code=403, detail="unexpected Origin")
    return {"token": session.TOKEN}


@router.websocket("/ui")
async def ui_websocket(websocket: WebSocket):
    # This socket streams every transcript, clipboard change and memory hit,
    # and accepts answers to confirmation prompts. Same-machine only unless
    # ALLOW_LAN_HUD; and a browser page must be this app's (Origin) holding
    # this process's session token.
    peer = websocket.client.host if websocket.client else None
    if not peer_allowed(peer):
        log.warning(f"Rejected /ws/ui from non-local address {peer!r}")
        await websocket.close(code=4403)
        return
    origin = websocket.headers.get("origin")
    if not session.origin_ok(origin, websocket.headers.get("host"), settings.allow_lan_hud):
        log.warning("Rejected /ws/ui from origin %r", origin)
        await websocket.close(code=4403)
        return
    if not session.token_ok(websocket.query_params.get("token")):
        log.warning("Rejected /ws/ui: missing or stale session token")
        # Accept, THEN close: a close before accept reaches a real browser as
        # a bare HTTP 403 / code 1006, so the HUD could never tell "stale
        # token, fetch a new one" (the backend restarted) from "server down".
        # Safe: the Origin already passed and nothing is sent before closing.
        await websocket.accept()
        await websocket.close(code=4401)
        return

    mgr = get_manager()
    await mgr.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "confirm_response":
                ok, message = await hud_confirm.answer(
                    str(msg.get("id", "")), str(msg.get("digest", "")),
                    "yes" if msg.get("decision") == "yes" else "no")
                await websocket.send_text(json.dumps({
                    "type": "confirmation_ack",
                    "payload": {"id": str(msg.get("id", "")), "ok": ok, "message": message},
                }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"Web UI WS error: {e}")
    finally:
        mgr.disconnect(websocket)
