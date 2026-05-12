from typing import Annotated

from fastapi import APIRouter, Depends

from backend.core.auth.deps import get_current_user
from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor.executor import execute as do_execute

router = APIRouter(prefix="/execute", tags=["execute"])


@router.post("")
def execute_endpoint(
    intent: Intent,
    _user: Annotated[dict, Depends(get_current_user)],
):
    return do_execute(intent).model_dump()
