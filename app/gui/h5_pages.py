"""
用户端 H5 页面路由。
主路径：/h5/*
别名：/patient/* → 301 重定向到 /h5/*
"""
from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.services.auth_service import decode_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["h5-pages"])


def _is_logged_in(access_token: str | None) -> bool:
    if not access_token:
        return False
    return decode_token(access_token) is not None


# ── /patient/* → 301 aliases ──

@router.get("/patient/{path:path}", response_class=RedirectResponse)
async def patient_redirect(path: str):
    return RedirectResponse(url=f"/h5/{path}", status_code=301)


@router.get("/patient", response_class=RedirectResponse)
async def patient_root_redirect():
    return RedirectResponse(url="/h5/home", status_code=301)


# ── H5 页面 ──

@router.get("/h5/home", response_class=HTMLResponse)
async def h5_home(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/h5/plan", status_code=302)


# ── 方案 Tab ──

@router.get("/h5/plan", response_class=HTMLResponse)
async def h5_plan(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/plan.html", {"request": request})


@router.get("/h5/plan/history", response_class=HTMLResponse)
async def h5_plan_history(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/plan_history.html", {"request": request})


@router.get("/h5/plan/documents", response_class=HTMLResponse)
async def h5_plan_documents(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/plan_documents.html", {"request": request})


@router.get("/h5/profile", response_class=HTMLResponse)
async def h5_profile(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/profile.html", {"request": request})


@router.get("/h5/indicators", response_class=HTMLResponse)
async def h5_indicators(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/indicators.html", {"request": request})


@router.get("/h5/indicators/add", response_class=HTMLResponse)
async def h5_indicators_add(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/indicators_add.html", {"request": request})


@router.get("/h5/constitution", response_class=HTMLResponse)
async def h5_constitution(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/constitution.html", {"request": request})


@router.get("/h5/constitution/assess", response_class=HTMLResponse)
async def h5_constitution_assess(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/constitution_assess.html", {"request": request})


@router.get("/h5/constitution/result/{assessment_id}", response_class=HTMLResponse)
async def h5_constitution_result(
    assessment_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "patient/constitution_result.html",
        {"request": request, "assessment_id": assessment_id},
    )


@router.get("/h5/followup", response_class=HTMLResponse)
async def h5_followup(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/followup_main.html", {"request": request})


# ── 我的 Tab ──

@router.get("/h5/me", response_class=HTMLResponse)
async def h5_me(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/me.html", {"request": request})


@router.get("/h5/recommendation", response_class=HTMLResponse)
async def h5_recommendation(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/recommendation.html", {"request": request})


@router.get("/h5/content", response_class=HTMLResponse)
async def h5_content(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/content_list.html", {"request": request})


@router.get("/h5/content/{content_id}", response_class=HTMLResponse)
async def h5_content_detail(
    content_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "patient/content_detail.html",
        {"request": request, "content_id": content_id},
    )


# ── 通知中心 ──

@router.get("/h5/notifications", response_class=HTMLResponse)
async def h5_notifications(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/notification_list.html", {"request": request})


# ── 在线咨询 ──

@router.get("/h5/consultation/new", response_class=HTMLResponse)
async def h5_consultation_new(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/consultation_new.html", {"request": request})


@router.get("/h5/consultation/{consult_id}", response_class=HTMLResponse)
async def h5_consultation_detail(
    consult_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "patient/consultation_detail.html",
        {"request": request, "consult_id": consult_id},
    )


# ── 我的调理方案 ──

@router.get("/h5/care-plan", response_class=HTMLResponse)
async def h5_care_plan(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/care_plan.html", {"request": request})


# ── 打卡 Tab ──

@router.get("/h5/checkin", response_class=HTMLResponse)
async def h5_checkin(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/checkin_main.html", {"request": request})


# ── 复诊/随访提醒 ──

@router.get("/h5/reminders", response_class=HTMLResponse)
async def h5_reminders(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/reminders.html", {"request": request})


# ── 复诊预约 ──

@router.get("/h5/appointment", response_class=HTMLResponse)
async def h5_appointment(request: Request, access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("patient/appointment.html", {"request": request})


# ── 调理方案详情 ──

@router.get("/h5/plan/{plan_id}", response_class=HTMLResponse)
async def h5_plan_detail(
    plan_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "patient/plan_detail.html",
        {"request": request, "plan_id": plan_id},
    )
