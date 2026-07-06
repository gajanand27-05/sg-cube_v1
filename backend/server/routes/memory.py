import logging

from fastapi import APIRouter, Query

from backend.core.events import get_bus
from backend.core.memory.manager import memory as memory_manager
from backend.daemon.ui_events import MemoryHitEvent

log = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


def _iso(ts) -> str | None:
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


@router.get("/search")
def search_memory(
    q: str = Query("", description="Search query"),
    limit: int = Query(10, description="Max results to return"),
):
    """Semantic search with composite scoring breakdown.

    Returns each result with the score components LTM.search uses
    internally (semantic / temporal / importance / confidence / access_boost)
    plus a human-readable explanation, so the UI can show relevance %.
    """
    if not q.strip():
        return {"results": []}
    try:
        # search_explainable returns [{entry, scores, explanation}, ...]
        candidates = memory_manager.ltm.search_explainable(q, limit=limit)
        get_bus().publish(MemoryHitEvent(query=q, source="semantic", results_count=len(candidates)))
        results = []
        for c in candidates:
            e = c["entry"]
            scores = c["scores"]
            results.append({
                "content": e.content,
                "type": e.mtype.value if hasattr(e.mtype, "value") else str(e.mtype),
                "timestamp": _iso(e.timestamp),
                "source": e.source,
                "importance": round(float(e.importance), 3),
                "confidence": round(float(e.confidence), 3),
                "tags": e.tags,
                "scores": scores,
                "explanation": c["explanation"],
                # Convenience: combined score expressed as a 0-100 percent for badges.
                "relevance_pct": round(float(scores.get("combined", 0.0)) * 100, 1),
            })
        return {"results": results}
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
                    "timestamp": _iso(e.timestamp),
                    "source": (e.metadata or {}).get("source"),
                    "type": e.mtype.value if hasattr(e.mtype, "value") else str(e.mtype),
                    "importance": round(float(getattr(e, "importance", 0.5)), 3),
                    "tags": getattr(e, "tags", []),
                }
                for e in entries
            ]
        }
    except Exception as e:
        log.warning(f"Recent memories failed: {e}")
        return {"results": []}
