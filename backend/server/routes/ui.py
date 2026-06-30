import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.server.ws_ui import get_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["ui"])


@router.websocket("/ui")
async def ui_websocket(websocket: WebSocket):
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
