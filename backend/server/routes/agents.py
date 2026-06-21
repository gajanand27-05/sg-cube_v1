import logging

from fastapi import APIRouter

from backend.core.agents.registry import registry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status")
def agents_status():
    return {
        "agents": registry.get_status(),
        "active_agent": registry.get_active_agent(),
    }
