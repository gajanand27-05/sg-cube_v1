import base64
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

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
    if latest_observation is None:
        return {"observation": None, "message": "No vision data captured yet"}
    return {"observation": latest_observation}
