"""
管理端 PC 页面路由。
主路径：/gui/admin/*
别名：/admin/* → 301 重定向到 /gui/admin/*
"""
from fastapi import APIRouter, Cookie, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.auth_service import decode_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["admin-pages"])


def _get_user_ctx(access_token: str | None) -> dict | None:
    """从 JWT 提取用户上下文，校验角色合法性。"""
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
        "name": payload.get("name") or ("管理员" if role == "ADMIN" else "医生"),
        "is_admin": role == "ADMIN",
    }


def _is_admin(access_token: str | None) -> bool:
    return _get_user_ctx(access_token) is not None


# ── /admin/* → 301 aliases ──

@router.get("/admin/{path:path}", response_class=RedirectResponse)
async def admin_redirect(path: str):
    return RedirectResponse(url=f"/gui/admin/{path}", status_code=301)


@router.get("/admin", response_class=RedirectResponse)
async def admin_root_redirect():
    return RedirectResponse(url="/gui/admin/workbench", status_code=301)


# ── 管理端 PC 页面 ──

@router.get("/gui/admin/alerts", response_class=HTMLResponse)
async def admin_alerts(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alerts.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/alerts/contacts", response_class=HTMLResponse)
async def admin_alert_contacts(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alert_contacts.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/alerts/batch", response_class=HTMLResponse)
async def admin_alert_batch(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alert_batch.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/alerts/{event_id}", response_class=HTMLResponse)
async def admin_alert_detail(
    event_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/alerts_detail.html",
        {"request": request, "event_id": event_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/content", response_class=HTMLResponse)
async def admin_content(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/content_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/content/new", response_class=HTMLResponse)
async def admin_content_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/content_edit.html", {"request": request, "content_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/content/{content_id}/edit", response_class=HTMLResponse)
async def admin_content_edit(
    content_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/content_edit.html",
        {"request": request, "content_id": content_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/audit", response_class=HTMLResponse)
async def admin_audit(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/audit.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/patients", response_class=HTMLResponse)
async def admin_patients(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/patients.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup", response_class=HTMLResponse)
async def admin_followup(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/workbench", response_class=HTMLResponse)
async def admin_workbench(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/workbench.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/assessments", response_class=HTMLResponse)
async def admin_assessments(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/assessments.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/guidance", response_class=HTMLResponse)
async def admin_guidance(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/guidance.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scales", response_class=HTMLResponse)
async def admin_scales(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scales.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/settings", response_class=HTMLResponse)
async def admin_mgmt_settings(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_settings.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/orgs", response_class=HTMLResponse)
async def admin_mgmt_orgs(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_orgs.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/roles", response_class=HTMLResponse)
async def admin_mgmt_roles(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_roles.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/tasks", response_class=HTMLResponse)
async def admin_mgmt_tasks(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_tasks.html", {"request": request, "user_ctx": ctx})


# ── 档案管理 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/archives", response_class=HTMLResponse)
async def admin_archives(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/families", response_class=HTMLResponse)
async def admin_archive_families(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_families.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/families/{family_id}", response_class=HTMLResponse)
async def admin_archive_family_detail(
    family_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/archive_family_detail.html",
        {"request": request, "family_id": family_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/archives/recycle", response_class=HTMLResponse)
async def admin_archive_recycle(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_recycle.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/children", response_class=HTMLResponse)
async def admin_archive_children(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_children.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/women", response_class=HTMLResponse)
async def admin_archive_women(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_women.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/elderly", response_class=HTMLResponse)
async def admin_archive_elderly(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_elderly.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/key-focus", response_class=HTMLResponse)
async def admin_archive_key_focus(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_key_focus.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/audit", response_class=HTMLResponse)
async def admin_archive_audit(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_audit_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/audit/{audit_id}", response_class=HTMLResponse)
async def admin_archive_audit_detail(
    audit_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/archive_audit_detail.html",
        {"request": request, "audit_id": audit_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/archives/my", response_class=HTMLResponse)
async def admin_my_archives(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/my_archives.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/transfer-log", response_class=HTMLResponse)
async def admin_archive_transfer_log(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/archive_transfer_log.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/archives/{archive_id}", response_class=HTMLResponse)
async def admin_archive_detail(
    archive_id: str,
    request: Request,
    from_page: str | None = Query(default=None, alias="from"),
    access_token: str | None = Cookie(default=None),
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")

    # 根据来源模块决定侧边栏高亮和面包屑
    _FROM_MAP = {
        "archives":  ("archives",         "档案查询",       "/gui/admin/archives"),
        "my":        ("my_archives",      "我的居民档案",   "/gui/admin/archives/my"),
        "families":  ("archive_families", "家庭档案",       "/gui/admin/archives/families"),
        "elderly":   ("archive_elderly",  "老年人档案",     "/gui/admin/archives/elderly"),
        "women":     ("archive_women",    "女性档案",       "/gui/admin/archives/women"),
        "children":  ("archive_children", "0-6岁儿童档案", "/gui/admin/archives/children"),
        "key-focus": ("archive_key_focus","重点关注人群",   "/gui/admin/archives/key-focus"),
    }
    active_nav, from_label, from_url = _FROM_MAP.get(
        from_page, ("archives", "档案管理", "/gui/admin/archives")
    )
    return templates.TemplateResponse(
        "admin/archive_detail.html",
        {
            "request": request,
            "archive_id": archive_id,
            "user_ctx": ctx,
            "active_nav": active_nav,
            "from_label": from_label,
            "from_url": from_url,
        },
    )


@router.get("/gui/admin/archives/new", response_class=HTMLResponse)
async def admin_archive_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/archive_edit.html",
        {"request": request, "archive_id": None, "user_ctx": ctx},
    )


@router.get("/gui/admin/archives/{archive_id}/edit", response_class=HTMLResponse)
async def admin_archive_edit(
    archive_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/archive_edit.html",
        {"request": request, "archive_id": archive_id, "user_ctx": ctx},
    )




# ── 综合就诊台 + 就诊数据 ─────────────────────────────────────────────

@router.get("/gui/admin/visit-station", response_class=HTMLResponse)
async def admin_visit_station(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/visit_station.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/clinical", response_class=HTMLResponse)
async def admin_clinical(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/clinical_list.html", {"request": request, "user_ctx": ctx})


# ── 统计分析扩展 ──────────────────────────────────────────────────────

# ── AI 风险诊断 & 在线咨询 ────────────────────────────────────────────

@router.get("/gui/admin/risk/plan", response_class=HTMLResponse)
async def admin_risk_plan(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/risk_plan.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/consultations", response_class=HTMLResponse)
async def admin_consultations(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/consultation_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/consultations/{consult_id}", response_class=HTMLResponse)
async def admin_consultation_detail(
    consult_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/consultation_detail.html",
        {"request": request, "consult_id": consult_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/stats/disease", response_class=HTMLResponse)
async def admin_stats_disease(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_disease.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/stats/workload", response_class=HTMLResponse)
async def admin_stats_workload(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_workload.html", {"request": request, "user_ctx": ctx})


# ── 管理中心扩展 ──────────────────────────────────────────────────────

@router.get("/gui/admin/mgmt/dict", response_class=HTMLResponse)
async def admin_mgmt_dict(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_dict.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/version", response_class=HTMLResponse)
async def admin_mgmt_version(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_version.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/logs", response_class=HTMLResponse)
async def admin_mgmt_logs(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_logs.html", {"request": request, "user_ctx": ctx})


# ── 体质评估详细页 ────────────────────────────────────────────────────

@router.get("/gui/admin/assessments/new", response_class=HTMLResponse)
async def admin_assess_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/assess_constitution_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/assessments/{assess_id}/answer", response_class=HTMLResponse)
async def admin_assess_answer(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_constitution_answer.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/assessments/{assess_id}/report", response_class=HTMLResponse)
async def admin_assess_report(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_constitution_report.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/assessments/{assess_id}", response_class=HTMLResponse)
async def admin_assess_detail(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_constitution_detail.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


# ── 健康评估 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/health-assess", response_class=HTMLResponse)
async def admin_health_assess(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/assess_health_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/health-assess/new", response_class=HTMLResponse)
async def admin_health_assess_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/assess_health_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/health-assess/{assess_id}", response_class=HTMLResponse)
async def admin_health_assess_detail(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_detail.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/health-assess/{assess_id}/report-edit", response_class=HTMLResponse)
async def admin_health_assess_report_edit(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_report_edit.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/health-assess/{assess_id}/report-detail", response_class=HTMLResponse)
async def admin_health_assess_report_detail(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_report_detail.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


# ── 量表评估 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/scale-library", response_class=HTMLResponse)
async def admin_scale_library(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scale_library.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scale-library/{scale_id}/preview", response_class=HTMLResponse)
async def admin_scale_library_preview(
    scale_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_preview.html",
        {"request": request, "scale_id": scale_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/scale-records", response_class=HTMLResponse)
async def admin_scale_records(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scale_records.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scale-answer/{scale_id}", response_class=HTMLResponse)
async def admin_scale_answer(
    scale_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_answer.html",
        {"request": request, "scale_id": scale_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/scale-result/{record_id}", response_class=HTMLResponse)
async def admin_scale_result(
    record_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_result.html",
        {"request": request, "record_id": record_id, "user_ctx": ctx},
    )


# ── 量表配置 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/scale-config", response_class=HTMLResponse)
async def admin_scale_config(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scale_config_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scale-config/new", response_class=HTMLResponse)
async def admin_scale_config_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_config_edit.html", {"request": request, "scale_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/scale-config/{scale_id}/edit", response_class=HTMLResponse)
async def admin_scale_config_edit(
    scale_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_config_edit.html",
        {"request": request, "scale_id": scale_id, "user_ctx": ctx},
    )


# ── 随访管理详细页 ────────────────────────────────────────────────────

@router.get("/gui/admin/followup/tasks", response_class=HTMLResponse)
async def admin_followup_tasks(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup_task_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup/new", response_class=HTMLResponse)
async def admin_followup_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup/rules", response_class=HTMLResponse)
async def admin_followup_rules(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup_rules.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup/rule/new", response_class=HTMLResponse)
async def admin_followup_rule_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/followup_rule_edit.html", {"request": request, "rule_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/followup/rule/{rule_id}/edit", response_class=HTMLResponse)
async def admin_followup_rule_edit(
    rule_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/followup_rule_edit.html",
        {"request": request, "rule_id": rule_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/followup/plan/new", response_class=HTMLResponse)
async def admin_followup_plan_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup_plan_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup/auto-log", response_class=HTMLResponse)
async def admin_followup_auto_log(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/followup_auto_log.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/followup/{task_id}/process", response_class=HTMLResponse)
async def admin_followup_process(
    task_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/followup_process.html",
        {"request": request, "task_id": task_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/followup/{task_id}", response_class=HTMLResponse)
async def admin_followup_detail(
    task_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/followup_task_detail.html",
        {"request": request, "task_id": task_id, "user_ctx": ctx},
    )


# ── 危急值规则管理 ────────────────────────────────────────────────────

@router.get("/gui/admin/alert-rules", response_class=HTMLResponse)
async def admin_alert_rules(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alert_rules.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/alert-rules/new", response_class=HTMLResponse)
async def admin_alert_rules_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/alert_rules_edit.html", {"request": request, "rule_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/alert-rules/{rule_id}/edit", response_class=HTMLResponse)
async def admin_alert_rules_edit(
    rule_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/alert_rules_edit.html",
        {"request": request, "rule_id": rule_id, "user_ctx": ctx},
    )


# ── 统计分析扩展 ──────────────────────────────────────────────────────

@router.get("/gui/admin/stats/archive", response_class=HTMLResponse)
async def admin_stats_archive(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_archive.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/stats/constitution", response_class=HTMLResponse)
async def admin_stats_constitution(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_constitution.html", {"request": request, "user_ctx": ctx})


# ── 中医干预 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/intervention", response_class=HTMLResponse)
async def admin_intervention(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/intervention_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/intervention/new", response_class=HTMLResponse)
async def admin_intervention_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/intervention_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/intervention/templates", response_class=HTMLResponse)
async def admin_intervention_templates(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/intervention_templates.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/intervention/templates/new", response_class=HTMLResponse)
async def admin_intervention_template_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/intervention_template_edit.html", {"request": request, "tpl_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/intervention/templates/{tpl_id}/edit", response_class=HTMLResponse)
async def admin_intervention_template_edit(
    tpl_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/intervention_template_edit.html",
        {"request": request, "tpl_id": tpl_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/intervention/{record_id}/execute", response_class=HTMLResponse)
async def admin_intervention_execute(
    record_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/intervention_plan_execute.html",
        {"request": request, "intervention_id": record_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/intervention/{record_id}", response_class=HTMLResponse)
async def admin_intervention_detail(
    record_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/intervention_detail.html",
        {"request": request, "record_id": record_id, "user_ctx": ctx},
    )


# ── 中医宣教 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/health-education", response_class=HTMLResponse)
async def admin_health_education(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/education_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/health-education/new", response_class=HTMLResponse)
async def admin_health_education_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/education_new.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/health-education/templates", response_class=HTMLResponse)
async def admin_education_templates(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/education_templates.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/health-education/templates/new", response_class=HTMLResponse)
async def admin_education_template_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/education_template_edit.html", {"request": request, "tpl_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/health-education/templates/{tpl_id}/edit", response_class=HTMLResponse)
async def admin_education_template_edit(
    tpl_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/education_template_edit.html",
        {"request": request, "tpl_id": tpl_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/health-education/{record_id}/execute", response_class=HTMLResponse)
async def admin_education_execute(
    record_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/education_plan_execute.html",
        {"request": request, "record_id": record_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/health-education/{record_id}", response_class=HTMLResponse)
async def admin_health_education_detail(
    record_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/education_detail.html",
        {"request": request, "record_id": record_id, "user_ctx": ctx},
    )


# ── 指导计划 & 模板库 ─────────────────────────────────────────────────

@router.get("/gui/admin/guidance/plans", response_class=HTMLResponse)
async def admin_guidance_plans(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/guidance_plans.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/guidance/templates", response_class=HTMLResponse)
async def admin_guidance_templates(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/guidance_templates.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/guidance/templates/new", response_class=HTMLResponse)
async def admin_guidance_template_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/guidance_template_edit.html", {"request": request, "tpl_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/guidance/templates/{tpl_id}/edit", response_class=HTMLResponse)
async def admin_guidance_template_edit(
    tpl_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/guidance_template_edit.html",
        {"request": request, "tpl_id": tpl_id, "user_ctx": ctx},
    )


# ── 管理中心扩展（参数配置、服务接口） ───────────────────────────────

@router.get("/gui/admin/mgmt/params", response_class=HTMLResponse)
async def admin_mgmt_params(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_params.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/services", response_class=HTMLResponse)
async def admin_mgmt_services(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_services.html", {"request": request, "user_ctx": ctx})


# ── 授权管理 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/mgmt/licenses", response_class=HTMLResponse)
async def admin_mgmt_licenses(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_licenses.html", {"request": request, "user_ctx": ctx})


# ── 权限栏目管理 ──────────────────────────────────────────────────────

@router.get("/gui/admin/mgmt/menus", response_class=HTMLResponse)
async def admin_mgmt_menus(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_menus.html", {"request": request, "user_ctx": ctx})


# ── 标签管理 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/labels", response_class=HTMLResponse)
async def admin_label_list(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/label_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/labels/stats", response_class=HTMLResponse)
async def admin_label_stats(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/label_stats.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/labels/{patient_id}", response_class=HTMLResponse)
async def admin_label_patient(
    patient_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/label_patient.html",
        {"request": request, "patient_id": patient_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/tools", response_class=HTMLResponse)
async def admin_tools(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/tools.html",
        {"request": request, "tools_registry": _build_tools_registry(), "user_ctx": ctx},
    )


def _build_tools_registry() -> list[dict]:
    """返回平台所有 Tool 的结构化描述，用于工具详情页渲染。"""
    return [
        {
            "group": "认证",
            "group_en": "auth",
            "icon": "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z",
            "color": "blue",
            "tools": [
                {
                    "method": "POST", "path": "/tools/auth/register",
                    "name": "用户注册",
                    "desc": "创建新患者账号，返回 JWT 并设置 Cookie。",
                    "role": "公开",
                    "params": [
                        {"name": "phone", "type": "string", "required": True, "desc": "手机号（唯一）"},
                        {"name": "password", "type": "string", "required": True, "desc": "密码（≥8位）"},
                        {"name": "name", "type": "string", "required": True, "desc": "真实姓名"},
                        {"name": "email", "type": "string", "required": False, "desc": "邮箱（可选）"},
                    ],
                },
                {
                    "method": "POST", "path": "/tools/auth/login",
                    "name": "用户登录",
                    "desc": "验证账号密码，成功后设置 HttpOnly Cookie（access_token）。",
                    "role": "公开",
                    "params": [
                        {"name": "phone", "type": "string", "required": True, "desc": "手机号"},
                        {"name": "password", "type": "string", "required": True, "desc": "密码"},
                    ],
                },
                {
                    "method": "POST", "path": "/tools/auth/logout",
                    "name": "退出登录",
                    "desc": "清除 access_token Cookie，使会话失效。",
                    "role": "已登录",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/auth/consent",
                    "name": "同意隐私协议",
                    "desc": "记录患者对指定版本隐私协议的同意操作（含 IP 和渠道）。",
                    "role": "已登录",
                    "params": [
                        {"name": "version", "type": "string", "required": True, "desc": "协议版本号"},
                        {"name": "channel", "type": "string", "required": False, "desc": "渠道标识"},
                    ],
                },
            ],
        },
        {
            "group": "健康档案",
            "group_en": "health",
            "icon": "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
            "color": "green",
            "tools": [
                {
                    "method": "GET", "path": "/tools/profile",
                    "name": "获取个人档案",
                    "desc": "返回当前用户的完整健康档案（基本信息、生活方式、病史）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/profile",
                    "name": "新建/更新档案",
                    "desc": "创建或更新健康档案，支持增量更新（仅传需修改的字段）。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "gender", "type": "string", "required": False, "desc": "性别：MALE / FEMALE"},
                        {"name": "birth_date", "type": "date", "required": False, "desc": "出生日期"},
                        {"name": "height_cm", "type": "number", "required": False, "desc": "身高（cm）"},
                        {"name": "weight_kg", "type": "number", "required": False, "desc": "体重（kg）"},
                        {"name": "smoking", "type": "boolean", "required": False, "desc": "是否吸烟"},
                        {"name": "drinking", "type": "boolean", "required": False, "desc": "是否饮酒"},
                    ],
                },
                {
                    "method": "POST", "path": "/tools/disease",
                    "name": "添加慢病记录",
                    "desc": "为患者添加慢性病诊断记录（高血压/2型糖尿病），包含用药和目标值。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "disease_type", "type": "string", "required": True, "desc": "病种：HYPERTENSION / DIABETES_T2"},
                        {"name": "diagnosed_at", "type": "date", "required": True, "desc": "确诊日期"},
                        {"name": "medications", "type": "array", "required": False, "desc": "用药列表（JSON）"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/disease",
                    "name": "查询慢病列表",
                    "desc": "返回当前用户的所有慢病记录。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/indicators",
                    "name": "录入健康指标",
                    "desc": "上传血压、血糖、体重或腰围数据，自动触发预警检测引擎。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "indicator_type", "type": "string", "required": True, "desc": "类型：BLOOD_PRESSURE / BLOOD_GLUCOSE / WEIGHT / WAIST_CIRCUMFERENCE"},
                        {"name": "values", "type": "object", "required": True, "desc": "指标值（血压：{systolic,diastolic}；血糖：{value}）"},
                        {"name": "scene", "type": "string", "required": False, "desc": "测量场景（晨起/餐前/餐后…）"},
                        {"name": "recorded_at", "type": "datetime", "required": False, "desc": "测量时间，默认当前时间"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/indicators",
                    "name": "查询指标历史",
                    "desc": "按类型、日期范围分页查询历史指标记录。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "indicator_type", "type": "string", "required": False, "desc": "指标类型（不填返回全部）"},
                        {"name": "start_date", "type": "date", "required": False, "desc": "开始日期"},
                        {"name": "end_date", "type": "date", "required": False, "desc": "结束日期"},
                        {"name": "page", "type": "integer", "required": False, "desc": "页码，默认 1"},
                        {"name": "page_size", "type": "integer", "required": False, "desc": "每页条数，默认 20"},
                    ],
                },
            ],
        },
        {
            "group": "九体质评估",
            "group_en": "constitution",
            "icon": "M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z",
            "color": "rose",
            "tools": [
                {
                    "method": "GET", "path": "/tools/constitution/questions",
                    "name": "获取题目列表",
                    "desc": "返回全部 72 道体质问卷题目（按体质分组）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/constitution/start",
                    "name": "开始体质评估",
                    "desc": "创建新的评估记录，返回 assessment_id，后续答题使用。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/constitution/answer",
                    "name": "保存答案",
                    "desc": "保存单题或批量答案，支持断点续答。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "assessment_id", "type": "string", "required": True, "desc": "评估记录 UUID"},
                        {"name": "answers", "type": "array", "required": True, "desc": "[{question_id, answer_value(1-5)}]"},
                    ],
                },
                {
                    "method": "POST", "path": "/tools/constitution/submit",
                    "name": "提交评估",
                    "desc": "提交全部答案，自动评分并生成体质报告与调护建议方案。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "assessment_id", "type": "string", "required": True, "desc": "评估记录 UUID"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/constitution/latest",
                    "name": "获取最新评估结果",
                    "desc": "返回最近一次已完成的体质评估结果（9种体质得分与等级）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "GET", "path": "/tools/constitution/recommendation",
                    "name": "获取调护建议",
                    "desc": "基于最新体质评估结果返回个性化调护方案（起居/饮食/运动/情志/外治）。",
                    "role": "PATIENT",
                    "params": [],
                },
            ],
        },
        {
            "group": "随访管理",
            "group_en": "followup",
            "icon": "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
            "color": "amber",
            "tools": [
                {
                    "method": "POST", "path": "/tools/followup/start",
                    "name": "开始随访计划",
                    "desc": "根据病种模板生成 30 天随访计划，自动创建每日打卡任务。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "disease_type", "type": "string", "required": True, "desc": "病种：HYPERTENSION / DIABETES_T2"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/followup/today",
                    "name": "获取今日任务",
                    "desc": "返回当天所有待完成的随访任务（指标上报/运动/服药/睡眠/饮食）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "POST", "path": "/tools/followup/checkin",
                    "name": "上报打卡",
                    "desc": "完成指定随访任务的打卡，记录数值数据（如血压值）。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "task_id", "type": "string", "required": True, "desc": "任务 UUID"},
                        {"name": "value", "type": "object", "required": False, "desc": "打卡数据（如血压：{systolic,diastolic}）"},
                        {"name": "note", "type": "string", "required": False, "desc": "备注"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/followup/adherence",
                    "name": "获取依从率",
                    "desc": "计算当前用户活跃随访计划的打卡依从率（已完成/应完成）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "GET", "path": "/tools/followup/plans",
                    "name": "查询随访计划列表",
                    "desc": "返回当前用户所有随访计划（含状态、起止日期）。",
                    "role": "PATIENT",
                    "params": [
                        {"name": "status", "type": "string", "required": False, "desc": "状态筛选：ACTIVE / COMPLETED / TERMINATED"},
                    ],
                },
            ],
        },
        {
            "group": "预警管理",
            "group_en": "alerts",
            "icon": "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
            "color": "red",
            "tools": [
                {
                    "method": "GET", "path": "/tools/alerts/",
                    "name": "我的预警列表",
                    "desc": "返回当前患者的所有预警事件（含严重程度、状态、触发值）。",
                    "role": "PATIENT",
                    "params": [],
                },
                {
                    "method": "GET", "path": "/tools/alerts/admin",
                    "name": "全量预警列表（管理）",
                    "desc": "返回所有患者的预警事件，支持按状态、严重程度、患者筛选和分页。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "status", "type": "string", "required": False, "desc": "OPEN / ACKED / CLOSED"},
                        {"name": "severity", "type": "string", "required": False, "desc": "LOW / MEDIUM / HIGH"},
                        {"name": "page", "type": "integer", "required": False, "desc": "页码"},
                        {"name": "page_size", "type": "integer", "required": False, "desc": "每页条数"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/alerts/{event_id}",
                    "name": "预警详情",
                    "desc": "返回单条预警事件详情，含触发指标原始值和规则内容。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "event_id", "type": "string", "required": True, "desc": "预警事件 UUID（路径参数）"},
                    ],
                },
                {
                    "method": "PATCH", "path": "/tools/alerts/{event_id}/ack",
                    "name": "确认预警",
                    "desc": "将 OPEN 预警标记为 ACKED，记录处置人和备注，触发审计日志。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "event_id", "type": "string", "required": True, "desc": "预警事件 UUID（路径参数）"},
                        {"name": "note", "type": "string", "required": False, "desc": "处置备注"},
                    ],
                },
                {
                    "method": "PATCH", "path": "/tools/alerts/{event_id}/close",
                    "name": "关闭预警",
                    "desc": "将预警标记为 CLOSED（最终状态），不可再变更。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "event_id", "type": "string", "required": True, "desc": "预警事件 UUID（路径参数）"},
                        {"name": "note", "type": "string", "required": False, "desc": "关闭说明"},
                    ],
                },
            ],
        },
        {
            "group": "教育内容",
            "group_en": "content",
            "icon": "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
            "color": "purple",
            "tools": [
                {
                    "method": "GET", "path": "/tools/content",
                    "name": "内容列表（已发布）",
                    "desc": "返回所有已发布的教育内容，支持分类筛选和关键词搜索。",
                    "role": "公开",
                    "params": [
                        {"name": "category", "type": "string", "required": False, "desc": "内容分类"},
                        {"name": "q", "type": "string", "required": False, "desc": "关键词搜索"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/content/{id}",
                    "name": "内容详情",
                    "desc": "返回单篇教育内容的完整正文。",
                    "role": "公开",
                    "params": [
                        {"name": "id", "type": "string", "required": True, "desc": "内容 UUID（路径参数）"},
                    ],
                },
                {
                    "method": "POST", "path": "/tools/content/admin",
                    "name": "创建内容",
                    "desc": "创建新教育内容，默认状态为 DRAFT，需经过审核后发布。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "title", "type": "string", "required": True, "desc": "标题"},
                        {"name": "body", "type": "string", "required": True, "desc": "正文（支持 Markdown）"},
                        {"name": "category", "type": "string", "required": True, "desc": "分类"},
                    ],
                },
                {
                    "method": "PATCH", "path": "/tools/content/{id}/admin",
                    "name": "更新内容",
                    "desc": "更新内容字段或状态（DRAFT→PENDING_REVIEW→PUBLISHED→OFFLINE）。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "id", "type": "string", "required": True, "desc": "内容 UUID（路径参数）"},
                        {"name": "status", "type": "string", "required": False, "desc": "新状态"},
                        {"name": "title", "type": "string", "required": False, "desc": "新标题"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/content/admin",
                    "name": "后台内容列表",
                    "desc": "返回所有状态（含草稿）的内容列表，用于管理后台。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "status", "type": "string", "required": False, "desc": "状态筛选"},
                    ],
                },
            ],
        },
        {
            "group": "审计日志",
            "group_en": "audit",
            "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01",
            "color": "slate",
            "tools": [
                {
                    "method": "GET", "path": "/tools/audit/logs",
                    "name": "查询操作日志",
                    "desc": "分页查询系统操作审计日志，支持按用户、操作类型、资源类型和时间范围过滤。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "user_id", "type": "string", "required": False, "desc": "操作人用户 ID"},
                        {"name": "action", "type": "string", "required": False, "desc": "操作类型（如 TOGGLE_USER_ACTIVE）"},
                        {"name": "resource_type", "type": "string", "required": False, "desc": "资源类型（如 User / AgentQuery）"},
                        {"name": "start", "type": "datetime", "required": False, "desc": "开始时间"},
                        {"name": "end", "type": "datetime", "required": False, "desc": "结束时间"},
                        {"name": "page", "type": "integer", "required": False, "desc": "页码，默认 1"},
                        {"name": "page_size", "type": "integer", "required": False, "desc": "每页条数，默认 20"},
                    ],
                },
            ],
        },
        {
            "group": "管理工具",
            "group_en": "admin",
            "icon": "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
            "color": "teal",
            "tools": [
                {
                    "method": "GET", "path": "/tools/admin/patients",
                    "name": "患者列表",
                    "desc": "分页返回所有患者账号，支持姓名/手机号搜索和启用状态筛选。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "q", "type": "string", "required": False, "desc": "姓名/手机号关键词"},
                        {"name": "is_active", "type": "boolean", "required": False, "desc": "启用状态筛选"},
                        {"name": "page", "type": "integer", "required": False, "desc": "页码"},
                        {"name": "page_size", "type": "integer", "required": False, "desc": "每页条数（最大 100）"},
                    ],
                },
                {
                    "method": "PATCH", "path": "/tools/admin/patients/{id}/toggle-active",
                    "name": "启用/禁用患者",
                    "desc": "切换患者账号的启用状态，记录审计日志。仅 ADMIN 可操作。",
                    "role": "ADMIN",
                    "params": [
                        {"name": "id", "type": "string", "required": True, "desc": "患者 UUID（路径参数）"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/admin/followup",
                    "name": "随访质控",
                    "desc": "返回所有活跃随访计划的依从率汇总，按依从率升序排列（最差排最前）。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "page", "type": "integer", "required": False, "desc": "页码"},
                        {"name": "page_size", "type": "integer", "required": False, "desc": "每页条数"},
                    ],
                },
                {
                    "method": "GET", "path": "/tools/admin/stats/overview",
                    "name": "统计概览",
                    "desc": "返回平台统计快照：患者总数/活跃数、开放/高危预警数、体质分布、整体依从率。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [],
                },
            ],
        },
        {
            "group": "智能助手（Agent）",
            "group_en": "agent",
            "icon": "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z",
            "color": "emerald",
            "tools": [
                {
                    "method": "POST", "path": "/tools/agent/execute",
                    "name": "执行自然语言指令",
                    "desc": "接收自然语言查询，由 Claude AI（claude-haiku-4-5）解析意图并调用内置工具执行，返回结构化结果与导航动作。每次执行自动写入审计日志（action=AGENT_EXECUTE）。可通过 Ctrl+K 快捷键在任意管理页面调用。",
                    "role": "ADMIN / PROFESSIONAL",
                    "params": [
                        {"name": "query", "type": "string", "required": True, "desc": "自然语言指令（1~500字）"},
                    ],
                    "sub_tools": [
                        {"name": "search_patients", "desc": "按姓名/手机号搜索患者"},
                        {"name": "get_alert_list", "desc": "查询预警事件（可按状态/严重程度筛选）"},
                        {"name": "get_followup_overview", "desc": "查看依从率最差的随访计划"},
                        {"name": "get_stats_overview", "desc": "获取平台整体统计数据"},
                        {"name": "ack_alert", "desc": "确认（处置）指定预警事件"},
                        {"name": "navigate_to", "desc": "跳转到指定管理页面"},
                    ],
                },
            ],
        },
    ]


# ── 活动档案 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/activity-archives", response_class=HTMLResponse)
async def admin_activity_archives(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/activity_archive_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/activity-archives/rules", response_class=HTMLResponse)
async def admin_activity_rules(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/activity_rule_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/activity-archives/rules/new", response_class=HTMLResponse)
async def admin_activity_rule_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/activity_rule_edit.html", {"request": request, "rule_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/activity-archives/generate-log", response_class=HTMLResponse)
async def admin_activity_generate_log(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/activity_generate_log.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/activity-archives/rules/{rule_id}/edit", response_class=HTMLResponse)
async def admin_activity_rule_edit(
    rule_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/activity_rule_edit.html",
        {"request": request, "rule_id": rule_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/activity-archives/{activity_id}", response_class=HTMLResponse)
async def admin_activity_archive_detail(
    activity_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/activity_archive_detail.html",
        {"request": request, "activity_id": activity_id, "user_ctx": ctx},
    )


# ── 量表分类 / 组合 / 版本 ────────────────────────────────────────────

@router.get("/gui/admin/scales/categories", response_class=HTMLResponse)
async def admin_scale_categories(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scale_category.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scales/combos", response_class=HTMLResponse)
async def admin_scale_combos(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/scale_combo_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/scales/combos/new", response_class=HTMLResponse)
async def admin_scale_combo_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_combo_edit.html", {"request": request, "combo_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/scales/combos/{combo_id}/edit", response_class=HTMLResponse)
async def admin_scale_combo_edit(
    combo_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_combo_edit.html",
        {"request": request, "combo_id": combo_id, "user_ctx": ctx},
    )


@router.get("/gui/admin/scales/{scale_id}/versions", response_class=HTMLResponse)
async def admin_scale_versions(
    scale_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/scale_version.html",
        {"request": request, "scale_id": scale_id, "user_ctx": ctx},
    )


# ── 健康评估审核 ──────────────────────────────────────────────────────

@router.get("/gui/admin/health-assess/{assess_id}/review", response_class=HTMLResponse)
async def admin_health_assess_review(
    assess_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_review.html",
        {"request": request, "assess_id": assess_id, "user_ctx": ctx},
    )


# ── 危急值通知模板 ────────────────────────────────────────────────────

@router.get("/gui/admin/alert-rules/notification-tpl", response_class=HTMLResponse)
async def admin_alert_notification_tpl(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/alert_notification_tpl.html", {"request": request, "user_ctx": ctx})


# ── 区域分布统计 ──────────────────────────────────────────────────────

@router.get("/gui/admin/stats/region", response_class=HTMLResponse)
async def admin_stats_region(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_region.html", {"request": request, "user_ctx": ctx})


# ── 业务运营统计 ──────────────────────────────────────────────────────

@router.get("/gui/admin/stats/business", response_class=HTMLResponse)
async def admin_stats_business(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/stats_business.html", {"request": request, "user_ctx": ctx})


# ── 系统用户管理 ──────────────────────────────────────────────────────

@router.get("/gui/admin/mgmt/users", response_class=HTMLResponse)
async def admin_mgmt_users(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/mgmt_user_list.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/mgmt/users/new", response_class=HTMLResponse)
async def admin_mgmt_user_new(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/mgmt_user_edit.html", {"request": request, "user_id": None, "user_ctx": ctx}
    )


@router.get("/gui/admin/mgmt/users/{user_id}/edit", response_class=HTMLResponse)
async def admin_mgmt_user_edit(
    user_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/mgmt_user_edit.html",
        {"request": request, "user_id": user_id, "user_ctx": ctx},
    )


# ── 个人报表 ──────────────────────────────────────────────────────────

@router.get("/gui/admin/personal/workload", response_class=HTMLResponse)
async def admin_personal_workload(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/personal_workload.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/personal/archive-stats", response_class=HTMLResponse)
async def admin_personal_archive_stats(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/personal_archive_stats.html", {"request": request, "user_ctx": ctx})


@router.get("/gui/admin/personal/settings", response_class=HTMLResponse)
async def admin_personal_settings(request: Request, access_token: str | None = Cookie(default=None)):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin/personal_settings.html", {"request": request, "user_ctx": ctx})


# ── 健康评估综合报告 ────────────────────────────────────────────────────

@router.get("/gui/admin/health-assess/comprehensive/new", response_class=HTMLResponse)
async def admin_health_assess_comprehensive_new(
    request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_comprehensive.html",
        {"request": request, "user_ctx": ctx},
    )


@router.get("/gui/admin/health-assess/comprehensive/{report_id}", response_class=HTMLResponse)
async def admin_health_assess_comp_detail(
    report_id: str, request: Request, access_token: str | None = Cookie(default=None)
):
    ctx = _get_user_ctx(access_token)
    if not ctx:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        "admin/assess_health_comp_detail.html",
        {"request": request, "report_id": report_id, "user_ctx": ctx},
    )
