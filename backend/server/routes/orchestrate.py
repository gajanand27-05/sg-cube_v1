from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.auth.deps import get_any_user
from backend.core.memory.manager import memory as memory_manager
from backend.core.orchestrator.llm_layer import LLMResolveError
from backend.core.orchestrator.router import process_input

router = APIRouter(tags=["chat"])


class ProcessRequest(BaseModel):
    text: str


@router.post("/orchestrate/process")
async def process(
    body: ProcessRequest,
    user: Annotated[dict, Depends(get_any_user)],
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        result = await process_input(body.text, user["profile"]["id"])
    except LLMResolveError as e:
        raise HTTPException(status_code=502, detail=f"LLM unavailable: {e}")

    return result.model_dump()


@router.post("/chat")
async def chat(
    body: ProcessRequest,
    user: Annotated[dict, Depends(get_any_user)],
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        result = await process_input(body.text, user["profile"]["id"])
    except LLMResolveError as e:
        return {"response": f"LLM unavailable: {e}", "status": "error"}

    reply = result.intent.args.get("spoken", "") or f"Executing: {result.intent.action} {result.intent.target}"
    return {
        "response": reply,
        "intent": result.intent.model_dump(),
        "status": result.status,
        "latency_ms": result.latency_ms,
    }


@router.get("/chat/history")
def chat_history(limit: int = 20):
    try:
        turns = memory_manager.stm.render()
        return {"history": turns[-limit:]}
    except Exception as e:
        return {"history": [], "error": str(e)}
