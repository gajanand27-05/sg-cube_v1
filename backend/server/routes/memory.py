import logging

from fastapi import APIRouter, Query

from backend.core.memory.manager import memory as memory_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/search")
def search_memory(q: str = Query("", description="Search query")):
    if not q.strip():
        return {"results": []}
    try:
        entries = memory_manager.ltm.search(q, limit=10)
        return {
            "results": [
                {
                    "content": e.content,
                    "type": e.mtype.value if hasattr(e.mtype, 'value') else str(e.mtype),
                }
                for e in entries
            ]
        }
    except Exception as e:
        log.warning(f"Memory search failed: {e}")
        return {"results": []}


@router.get("/recent")
def recent_memories(limit: int = Query(20, description="Number of recent entries")):
    try:
        entries = memory_manager.timeline.get_recent_timeline(limit=limit)
        return {
            "results": [
                {
                    "content": e.content,
                    "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                    "source": e.metadata.get("source") if e.metadata else None,
                }
                for e in entries
            ]
        }
    except Exception as e:
        log.warning(f"Recent memories failed: {e}")
        return {"results": []}
