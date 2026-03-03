"""
管理端 PC 页面路由。
主路径：/gui/admin/*
别名：/admin/* → 301 重定向到 /gui/admin/*
"""
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_service import decode_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["admin-pages"])


def _is_admin(access_token: str | None) -> bool:
    if not access_token:
        return False
    payload = decode_token(access_token)
    if payload is None:
        return False
    return payload.get("role") in ("ADMIN", "PROFESSIONAL")


# ── /admin/* → 301 aliases ──

@router.get("/admin/{path:path}", response_class=RedirectResponse)
async def admin_redirect(path: str):
    return RedirectResponse(url=f"/gui/admin/{path}", status_code=301)


@router.get("/admin", response_class=RedirectResponse)
async def admin_root_redirect():
    return RedirectResponse(url="/gui/admin/alerts", status_code=301)


# ── 管理端 PC 页面 ──

@router.get("/gui/admin/alerts", response_class=HTMLResponse)
async def admin_alerts(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alerts.html", {"request": request})


@router.get("/gui/admin/alerts/{event_id}", response_class=HTMLResponse)
async def admin_alert_detail(
    event_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/alerts_detail.html",
        {"request": request, "event_id": event_id},
    )


@router.get("/gui/admin/content", response_class=HTMLResponse)
async def admin_content(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/content_list.html", {"request": request})


@router.get("/gui/admin/content/new", response_class=HTMLResponse)
async def admin_content_new(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/content_edit.html", {"request": request, "content_id": None})


@router.get("/gui/admin/content/{content_id}/edit", response_class=HTMLResponse)
async def admin_content_edit(
    content_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/content_edit.html",
        {"request": request, "content_id": content_id},
    )


@router.get("/gui/admin/audit", response_class=HTMLResponse)
async def admin_audit(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_admin(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/audit.html", {"request": request})
