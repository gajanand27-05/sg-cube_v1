import base64
import logging
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.core.vision.capture import capture_screen

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])


@router.get("/screenshot")
def get_screenshot():
    img_b64, window_title = capture_screen()
    if not img_b64:
        raise HTTPException(status_code=500, detail="Screen capture failed")
    img_bytes = base64.b64decode(img_b64)
    return Response(content=img_bytes, media_type="image/jpeg")
