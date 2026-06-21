import base64
import logging

import pygetwindow as gw
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.core.memory.screen_memory import screen_memory
from backend.core.vision.capture import capture_screen
from backend.daemon.vision_loop import latest_observation

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])


@router.get("/screenshot")
def get_screenshot():
    img_b64, window_title = capture_screen()
    if not img_b64:
        raise HTTPException(status_code=500, detail="Screen capture failed")
    img_bytes = base64.b64decode(img_b64)
    return Response(content=img_bytes, media_type="image/jpeg")


@router.get("/latest")
def get_latest_vision():
    return {
        "observation": latest_observation,
        "active_window": latest_observation.get("app") if latest_observation else None,
    }


@router.get("/observations")
def get_observations(limit: int = Query(20, description="Number of recent observations")):
    try:
        entries = screen_memory.get_recent_observations(limit=limit)
        return {"observations": entries}
    except Exception as e:
        log.warning(f"Failed to get observations: {e}")
        return {"observations": []}


@router.get("/windows")
def list_windows():
    try:
        windows = gw.getAllTitles()
        active = gw.getActiveWindow()
        return {
            "active": active.title if active else None,
            "windows": sorted([w for w in windows if w.strip()]),
        }
    except Exception as e:
        log.warning(f"Failed to list windows: {e}")
        return {"active": None, "windows": []}


@router.get("/memory/search")
def search_visual_memory(q: str = Query("", description="Search visual memory"), limit: int = Query(5)):
    if not q.strip():
        return {"results": []}
    try:
        entries = screen_memory.search_visual(q, limit=limit)
        return {
            "results": [
                {
                    "content": e.content,
                    "app": e.metadata.get("app", "Unknown"),
                    "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                }
                for e in entries
            ]
        }
    except Exception as e:
        log.warning(f"Visual memory search failed: {e}")
        return {"results": []}
