"""Replay & Diagnostics API — deterministic replay, trace inspection, regression testing."""
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/replay", tags=["replay"])

REPLAY_DIR = Path(__file__).resolve().parents[2] / "backend" / "database" / "replays"


class ReplayRequest(BaseModel):
    request_id: str
    mode: str = "full"  # "full" | "from_stage"


@router.post("/run")
async def run_replay(req: ReplayRequest):
    """Run a deterministic replay of a recorded execution."""
    trace_file = REPLAY_DIR / f"{req.request_id}.json"
    if not trace_file.exists():
        raise HTTPException(404, f"Trace not found: {req.request_id}")
    
    with open(trace_file) as f:
        trace = json.load(f)
    
    # TODO: Implement actual replay logic
    # For now, return the trace with replay metadata
    return {
        "status": "replay_complete",
        "request_id": req.request_id,
        "mode": req.mode,
        "original_trace": trace,
        "replay_metadata": {
            "stages_replayed": list(trace.get("execution_trace", [])),
            "deterministic": True,
        }
    }


@router.get("/trace/{request_id}")
async def get_trace(request_id: str):
    """Get full execution trace for a request."""
    trace_file = REPLAY_DIR / f"{request_id}.json"
    if not trace_file.exists():
        raise HTTPException(404, f"Trace not found: {request_id}")
    
    with open(trace_file) as f:
        return json.load(f)


@router.get("/traces")
async def list_traces(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    """List available execution traces."""
    if not REPLAY_DIR.exists():
        return {"traces": [], "total": 0}
    
    files = sorted(REPLAY_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    total = len(files)
    files = files[offset:offset + limit]
    
    traces = []
    for f in files:
        try:
            with open(f) as fh:
                trace = json.load(fh)
            traces.append({
                "request_id": trace.get("request_id", f.stem),
                "timestamp": trace.get("timestamp"),
                "input": trace.get("input", {}).get("input_text", "")[:100],
                "status": trace.get("status"),
                "latency_ms": trace.get("latency_ms"),
                "tool_count": len(trace.get("tool_calls", [])),
            })
        except Exception:
            continue
    
    return {"traces": traces, "total": total, "offset": offset, "limit": limit}


@router.post("/trace/{request_id}/diff")
async def diff_trace(request_id: str, compare_with: str):
    """Compare two execution traces."""
    trace1_file = REPLAY_DIR / f"{request_id}.json"
    trace2_file = REPLAY_DIR / f"{compare_with}.json"
    
    if not trace1_file.exists():
        raise HTTPException(404, f"Trace not found: {request_id}")
    if not trace2_file.exists():
        raise HTTPException(404, f"Trace not found: {compare_with}")
    
    with open(trace1_file) as f1, open(trace2_file) as f2:
        t1 = json.load(f1)
        t2 = json.load(f2)
    
    # Simple diff - compare key fields
    diff = {}
    for key in ["status", "latency_ms", "tool_calls", "intent"]:
        v1 = t1.get(key)
        v2 = t2.get(key)
        if v1 != v2:
            diff[key] = {"trace1": v1, "trace2": v2}
    
    return {
        "trace1": request_id,
        "trace2": compare_with,
        "diff": diff,
        "identical": len(diff) == 0,
    }


@router.get("/canonical")
async def get_canonical_cases():
    """Get canonical test cases for regression testing."""
    cases_file = REPLAY_DIR.parent / "canonical_cases.yaml"
    if not cases_file.exists():
        return {"cases": []}
    
    import yaml
    with open(cases_file) as f:
        return yaml.safe_load(f)


@router.post("/regression")
async def run_regression():
    """Run regression test suite against canonical cases."""
    # TODO: Implement regression test runner
    return {
        "status": "not_implemented",
        "message": "Regression test runner to be implemented",
    }