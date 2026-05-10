from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.core.auth.deps import require_admin
from backend.database.supabase_client import get_service_client

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/requests")
def list_requests(_admin: Annotated[dict, Depends(require_admin)]):
    sb = get_service_client()
    res = (
        sb.table("admin_requests")
        .select("*")
        .eq("status", "pending")
        .order("requested_at", desc=False)
        .execute()
    )
    return res.data


@router.post("/approve/{user_id}")
def approve(user_id: str, _admin: Annotated[dict, Depends(require_admin)]):
    sb = get_service_client()

    profile = (
        sb.table("profiles").select("id").eq("id", user_id).maybe_single().execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="User not found")

    sb.table("profiles").update(
        {"role": "admin", "is_approved_admin": True}
    ).eq("id", user_id).execute()

    sb.table("admin_requests").update(
        {"status": "approved", "resolved_at": datetime.now(timezone.utc).isoformat()}
    ).eq("user_id", user_id).eq("status", "pending").execute()

    return {"status": "approved", "user_id": user_id}


@router.post("/reject/{user_id}")
def reject(user_id: str, _admin: Annotated[dict, Depends(require_admin)]):
    sb = get_service_client()
    sb.table("admin_requests").update(
        {"status": "rejected", "resolved_at": datetime.now(timezone.utc).isoformat()}
    ).eq("user_id", user_id).eq("status", "pending").execute()
    return {"status": "rejected", "user_id": user_id}
