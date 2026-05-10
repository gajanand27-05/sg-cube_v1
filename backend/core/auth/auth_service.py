from fastapi import HTTPException, status

from backend.database.supabase_client import get_anon_client, get_service_client


def register(email: str, password: str, role: str = "user") -> dict:
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")

    svc = get_service_client()
    try:
        result = svc.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {e}")

    if not result.user:
        raise HTTPException(status_code=400, detail="Signup did not return a user")

    user_id = result.user.id

    if role == "admin":
        svc.table("admin_requests").insert(
            {"user_id": user_id, "status": "pending"}
        ).execute()
        return {
            "status": "pending",
            "user_id": user_id,
            "message": "Admin request submitted; awaiting approval",
        }

    return {"status": "success", "user_id": user_id}


def login(email: str, password: str, role: str = "user") -> dict:
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")

    sb = get_anon_client()
    try:
        result = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Login failed: {e}")

    if not result.session or not result.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    user_id = result.user.id

    svc = get_service_client()
    profile_res = (
        svc.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
    )
    profile = profile_res.data
    if not profile:
        raise HTTPException(
            status_code=500,
            detail="Profile row missing — signup trigger may not be installed",
        )

    if role == "admin" and (
        profile["role"] != "admin" or not profile["is_approved_admin"]
    ):
        return {
            "status": "pending",
            "user_id": user_id,
            "message": "Admin not yet approved",
        }

    return {
        "status": "success",
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
        "user_id": user_id,
        "profile": profile,
    }
