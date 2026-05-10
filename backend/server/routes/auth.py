from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.core.auth.auth_service import login as svc_login
from backend.core.auth.auth_service import register as svc_register
from backend.core.auth.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)
    role: Literal["user", "admin"] = "user"


class LoginRequest(BaseModel):
    email: str
    password: str
    role: Literal["user", "admin"] = "user"


@router.post("/register")
def register(body: RegisterRequest):
    return svc_register(body.email, body.password, body.role)


@router.post("/login")
def login(body: LoginRequest):
    return svc_login(body.email, body.password, body.role)


@router.get("/whoami")
def whoami(user: Annotated[dict, Depends(get_current_user)]):
    return user["profile"]
