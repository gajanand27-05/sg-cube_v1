import logging

from fastapi import APIRouter, Depends

from backend.core.agents.registry import get_registry
from backend.core.auth.deps import require_local_peer

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_local_peer)])


@router.get("/status")
def agents_status():
    registry = get_registry()
    return {
        "agents": registry.get_status(),
        "active_agent": registry.get_active_agent(),
    }
