import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.ai_modules.speech.stt_whisper import transcribe
from backend.ai_modules.speech.tts_piper import speak
from backend.core.auth.deps import get_current_user
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.router import process_input
from backend.core.safe_executor.executor import ExecutionResult
from backend.core.safe_executor.executor import execute as do_execute

router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


class SayRequest(BaseModel):
    text: str


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


@router.post("/say")
def say_endpoint(
    body: SayRequest,
    _user: Annotated[dict, Depends(get_current_user)],
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    return speak(body.text)


def _build_spoken_response(intent: Intent, exec_result: ExecutionResult) -> str:
    status = exec_result.status
    action = intent.action
    target = intent.target

    if status == "success":
        if action == "open_app":
            return f"Opening {target}"
        if action == "close_app":
            return f"Closing {target}"
        if action == "get_time":
            return f"The time is {exec_result.message}"
        return "Done"

    if status == "blocked":
        if action == "unknown":
            return "Sorry, I didn't understand"
        return "Sorry, that command is not allowed"

    return "Something went wrong"


@router.post("/process")
async def process_endpoint(
    audio: Annotated[UploadFile, File()],
    user: Annotated[dict, Depends(get_current_user)],
):
    """End-to-end voice loop: audio → STT → orchestrate → execute → TTS reply."""
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
        # 1. STT
        t0 = time.perf_counter()
        stt = transcribe(tmp_path)
        stt_ms = int((time.perf_counter() - t0) * 1000)
        transcript = stt["text"].strip()

        if not transcript:
            spoken = "Sorry, I did not hear anything"
            t_tts = time.perf_counter()
            speak(spoken)
            tts_ms = int((time.perf_counter() - t_tts) * 1000)
            return {
                "transcript": "",
                "intent": None,
                "source_layer": None,
                "execution": None,
                "spoken_text": spoken,
                "timings": {
                    "stt_ms": stt_ms,
                    "tts_ms": tts_ms,
                    "total_ms": stt_ms + tts_ms,
                },
            }

        # 2. Orchestrate
        t1 = time.perf_counter()
        try:
            router_result = process_input(transcript, user["profile"]["id"])
        except LLMResolveError as e:
            spoken = "Sorry, my reasoning model is unavailable"
            speak(spoken)
            raise HTTPException(status_code=502, detail=f"LLM unavailable: {e}")
        orch_ms = int((time.perf_counter() - t1) * 1000)

        # 3. Execute
        t2 = time.perf_counter()
        exec_result = do_execute(router_result.intent)
        exec_ms = int((time.perf_counter() - t2) * 1000)

        # 4. Speak response
        spoken = _build_spoken_response(router_result.intent, exec_result)
        t3 = time.perf_counter()
        speak(spoken)
        tts_ms = int((time.perf_counter() - t3) * 1000)

        return {
            "transcript": transcript,
            "intent": router_result.intent.model_dump(),
            "source_layer": router_result.source_layer,
            "execution": exec_result.model_dump(),
            "spoken_text": spoken,
            "timings": {
                "stt_ms": stt_ms,
                "orchestrate_ms": orch_ms,
                "execute_ms": exec_ms,
                "tts_ms": tts_ms,
                "total_ms": stt_ms + orch_ms + exec_ms + tts_ms,
            },
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)
