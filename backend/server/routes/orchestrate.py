from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.auth.deps import get_current_user
from backend.core.orchestrator.llm_layer import LLMResolveError
from backend.core.orchestrator.router import process_input

router = APIRouter(prefix="/orchestrate", tags=["orchestrate"])


class ProcessRequest(BaseModel):
    text: str


@router.post("/process")
def process(
    body: ProcessRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        result = process_input(body.text, user["profile"]["id"])
    except LLMResolveError as e:
        raise HTTPException(status_code=502, detail=f"LLM unavailable: {e}")

    return result.model_dump()
