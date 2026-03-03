from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models.enums import UserRole
from app.models.user import ConsentRecord, User
from app.services.audit_service import log_action
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.tools.response import fail, ok

router = APIRouter(prefix="/auth", tags=["auth-tools"])


class LoginRequest(BaseModel):
    phone: str
    password: str


class RegisterRequest(BaseModel):
    phone: str
    password: str
    name: str
    role: UserRole = UserRole.PATIENT


class ConsentRequest(BaseModel):
    version: str = "1.0"


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.phone == body.phone))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        return fail("VALIDATION_ERROR", "手机号或密码错误", status_code=401)
    if not user.is_active:
        return fail("PERMISSION_ERROR", "账号已禁用", status_code=403)

    token = create_access_token(
        {"sub": str(user.id), "role": user.role.value, "name": user.name},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    await log_action(
        db, action="LOGIN", resource_type="User", user_id=user.id,
        resource_id=str(user.id), ip_address=request.client.host if request.client else None
    )
    await db.commit()

    response = ok({"user_id": str(user.id), "role": user.role.value, "name": user.name})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


@router.post("/register")
async def register(
    body: RegisterRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.execute(select(User).where(User.phone == body.phone))
    if existing.scalar_one_or_none():
        return fail("VALIDATION_ERROR", "该手机号已注册", status_code=400)

    user = User(
        phone=body.phone,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    await log_action(
        db, action="REGISTER", resource_type="User", user_id=user.id,
        resource_id=str(user.id),
        new_values={"phone": body.phone, "name": body.name, "role": body.role.value},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return ok({"user_id": str(user.id)}, status_code=201)


@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):
    response = ok({"message": "已退出登录"})
    response.delete_cookie("access_token")
    return response


@router.post("/consent")
async def consent(
    body: ConsentRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    record = ConsentRecord(
        user_id=current_user.id,
        version=body.version,
        ip_address=request.client.host if request.client else None,
        channel="web",
    )
    db.add(record)
    await log_action(
        db, action="CONSENT", resource_type="ConsentRecord",
        user_id=current_user.id,
        new_values={"version": body.version},
    )
    await db.commit()
    return ok({"consented": True, "version": body.version})
