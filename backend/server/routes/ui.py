import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.auth.deps import peer_allowed
from backend.server.ws_ui import get_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["ui"])


@router.websocket("/ui")
async def ui_websocket(websocket: WebSocket):
    # This socket streams every transcript, clipboard change and memory hit,
    # and carries no credential. Same-machine only unless ALLOW_LAN_HUD.
    peer = websocket.client.host if websocket.client else None
    if not peer_allowed(peer):
        log.warning(f"Rejected /ws/ui from non-local address {peer!r}")
        await websocket.close(code=4403)
        return
    mgr = get_manager()
    await mgr.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"Web UI WS error: {e}")
    finally:
        mgr.disconnect(websocket)
