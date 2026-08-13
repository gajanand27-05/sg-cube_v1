from typing import Annotated

from fastapi import APIRouter, Depends

from backend.core.auth.deps import get_any_user
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor.executor import execute as do_execute

router = APIRouter(prefix="/execute", tags=["execute"])


@router.post("")
async def execute_endpoint(
    intent: Intent,
    _user: Annotated[dict, Depends(get_any_user)],
):
    # do_execute is a coroutine function. A sync handler here returned the
    # un-awaited coroutine, so .model_dump() raised AttributeError and every
    # POST /execute 500'd. Same shape was live in routes/voice.py.
    return (await do_execute(intent)).model_dump()
