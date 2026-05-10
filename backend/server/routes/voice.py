import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.ai_modules.speech.stt_whisper import transcribe
from backend.core.auth.deps import get_current_user

router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


@router.post("/transcribe")
async def transcribe_endpoint(
    audio: Annotated[UploadFile, File()],
    _user: Annotated[dict, Depends(get_current_user)],
):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="audio file required")

    ext = Path(audio.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported extension {ext}; allowed: {sorted(ALLOWED_EXTS)}",
        )

    contents = await audio.read()
    if not contents:
        raise HTTPException(status_code=400, detail="audio file is empty")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        t0 = time.perf_counter()
        result = transcribe(tmp_path)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {**result, "latency_ms": latency_ms}
    finally:
        Path(tmp_path).unlink(missing_ok=True)
