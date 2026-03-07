"""
HIS 端页面路由（模拟 HIS 系统）
主路径：/gui/his/*
"""
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_service import decode_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["his-pages"])


def _get_user_ctx(access_token: str | None) -> dict | None:
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    role = payload.get("role")
    if role not in ("ADMIN", "PROFESSIONAL"):
        return None
    return {
        "role": role,
        "name": payload.get("name") or "医生",
    }


@router.get("/gui/his/workstation", response_class=HTMLResponse)
async def his_workstation(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("his/workstation.html", {"request": request, "user_ctx": ctx})
