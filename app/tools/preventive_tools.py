"""
治未病·预防保健方案 API
前缀: /tools/preventive

全套 API 对应规格文档 §4 和 §5：
  POST   /lifestyle/extract               — 从对话提取生活方式
  POST   /lifestyle                       — 创建/更新生活方式档案
  GET    /lifestyle/{id}                  — 获取档案
  GET    /lifestyle?patient_id=...        — 患者档案列表
  POST   /tcm-assessments                 — 生成中医特征评估
  GET    /tcm-assessments/{id}            — 获取评估
  POST   /risk-inferences                 — 生成未来风险推断
  GET    /risk-inferences/{id}            — 获取风险推断
  GET    /packages/recommend              — 套餐推荐
  POST   /plans                           — 新建方案草稿
  GET    /plans                           — 方案列表
  GET    /plans/{id}                      — 方案详情
  PATCH  /plans/{id}                      — 更新方案草稿
  GET    /plans/{id}/preview              — 方案完整预览
  POST   /plans/{id}/confirm              — 确认方案
  POST   /plans/{id}/distribute           — 分发方案
  POST   /plans/{id}/confirm-and-distribute — 一步确认+分发
  POST   /plans/{id}/followups            — 生成随访任务
  GET    /plans/{id}/followups            — 随访任务列表
  PATCH  /followups/{task_id}             — 更新随访任务状态
  POST   /intents                         — 创建意向/预约
  GET    /intents?patient_id=...          — 意向列表
  PATCH  /intents/{id}                    — 更新意向状态
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import (
    DistributionChannel, IntentStatus, IntentType,
    LifestyleSource, PreventivePlanStatus, PreventiveTaskStatus, UserRole,
)
from app.models.preventive import (
    LifestyleProfile, PatientIntent, PlanDistribution,
    PreventiveFollowUpTask, PreventivePlan, RiskInference, TcmTraitAssessment,
)
from app.services.audit_service import log_action
from app.services import preventive_service as svc
from app.tools.response import fail, ok

router = APIRouter(prefix="/preventive", tags=["preventive"])

_PRO_OR_ADMIN = require_role(UserRole.PROFESSIONAL, UserRole.ADMIN)


# ──────────────────────────────────────────────────────────────────────────────
# 序列化辅助
# ──────────────────────────────────────────────────────────────────────────────

def _lp_dict(lp: LifestyleProfile) -> dict:
    return {
        "id": str(lp.id),
        "patient_id": str(lp.patient_id),
        "encounter_id": lp.encounter_id,
        "source": lp.source.value,
        "items": lp.items,
        "created_at": lp.created_at.isoformat(),
    }


def _ta_dict(ta: TcmTraitAssessment) -> dict:
    return {
        "id": str(ta.id),
        "patient_id": str(ta.patient_id),
        "lifestyle_profile_id": str(ta.lifestyle_profile_id) if ta.lifestyle_profile_id else None,
        "primary_trait": ta.primary_trait,
        "traits": ta.traits,
        "secondary_traits": ta.secondary_traits,
        "symptom_items": ta.symptom_items,
        "created_at": ta.created_at.isoformat(),
    }


def _ri_dict(ri: RiskInference) -> dict:
    return {
        "id": str(ri.id),
        "patient_id": str(ri.patient_id),
        "lifestyle_profile_id": str(ri.lifestyle_profile_id) if ri.lifestyle_profile_id else None,
        "risks": ri.risks,
        "rationale_chain": ri.rationale_chain,
        "vitals_snapshot": ri.vitals_snapshot,
        "created_at": ri.created_at.isoformat(),
    }


def _plan_dict(plan: PreventivePlan) -> dict:
    return {
        "id": str(plan.id),
        "patient_id": str(plan.patient_id),
        "encounter_id": plan.encounter_id,
        "status": plan.status.value,
        "version": plan.version,
        "summary_blocks": plan.summary_blocks,
        "selected_packages": plan.selected_packages,
        "selected_items": plan.selected_items,
        "economic_options": plan.economic_options,
        "doctor_note": plan.doctor_note,
        "patient_readable_note": plan.patient_readable_note,
        "created_by": str(plan.created_by) if plan.created_by else None,
        "confirmed_by": str(plan.confirmed_by) if plan.confirmed_by else None,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }


def _task_dict(t: PreventiveFollowUpTask) -> dict:
    return {
        "id": str(t.id),
        "patient_id": str(t.patient_id),
        "plan_id": str(t.plan_id),
        "task_type": t.task_type.value,
        "status": t.status.value,
        "due_at": t.due_at.isoformat(),
        "result_payload": t.result_payload,
        "created_at": t.created_at.isoformat(),
    }


def _intent_dict(i: PatientIntent) -> dict:
    return {
        "id": str(i.id),
        "patient_id": str(i.patient_id),
        "plan_id": str(i.plan_id) if i.plan_id else None,
        "type": i.type.value,
        "status": i.status.value,
        "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
        "location": i.location,
        "contact": i.contact,
        "note": i.note,
        "created_at": i.created_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# § A  生活方式档案
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/lifestyle/extract")
async def extract_lifestyle(
    body: dict = Body(...),
    _=Depends(get_current_user),
):
    """从对话文本 AI 提取生活方式条目（不持久化）。"""
    dialogue_text = (body.get("dialogue_text") or "").strip()
    if not dialogue_text:
        return fail("VALIDATION_ERROR", "dialogue_text 不能为空", status_code=400)
    items = await svc.extract_lifestyle_from_dialogue(dialogue_text)
    return ok({"items": items, "count": len(items)})


@router.post("/lifestyle")
async def create_lifestyle_profile(
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """创建生活方式档案。"""
    patient_id_str = body.get("patient_id")
    if not patient_id_str:
        return fail("VALIDATION_ERROR", "patient_id 不能为空", status_code=400)
    try:
        patient_id = uuid.UUID(str(patient_id_str))
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    items = body.get("items", [])
    if not isinstance(items, list):
        return fail("VALIDATION_ERROR", "items 必须是数组", status_code=400)

    source_raw = body.get("source", LifestyleSource.MANUAL.value)
    try:
        source = LifestyleSource(source_raw)
    except ValueError:
        source = LifestyleSource.MANUAL

    profile = await svc.upsert_lifestyle_profile(
        db=db,
        patient_id=patient_id,
        items=items,
        source=source,
        encounter_id=body.get("encounter_id"),
        raw_dialogue=body.get("raw_dialogue"),
        created_by=current_user.id,
    )
    await log_action(db, action="CREATE_LIFESTYLE_PROFILE", resource_type="LifestyleProfile",
                     user_id=current_user.id, resource_id=str(profile.id))
    await db.commit()
    return ok({"lifestyle_profile_id": str(profile.id)}, status_code=201)


@router.get("/lifestyle/{profile_id}")
async def get_lifestyle_profile(
    profile_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "profile_id 格式无效", status_code=400)
    lp = await db.get(LifestyleProfile, pid)
    if not lp:
        return fail("NOT_FOUND", "生活方式档案不存在", status_code=404)
    return ok(_lp_dict(lp))


@router.get("/lifestyle")
async def list_lifestyle_profiles(
    patient_id: str = Query(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        pid = uuid.UUID(patient_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)
    r = await db.execute(
        select(LifestyleProfile)
        .where(LifestyleProfile.patient_id == pid)
        .order_by(desc(LifestyleProfile.created_at))
        .limit(20)
    )
    items = [_lp_dict(lp) for lp in r.scalars().all()]
    return ok({"items": items, "total": len(items)})


# ══════════════════════════════════════════════════════════════════════════════
# § B  中医特征评估
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/tcm-assessments")
async def create_tcm_assessment(
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """生成中医特征评估（AI 推断）。"""
    patient_id_str = body.get("patient_id")
    if not patient_id_str:
        return fail("VALIDATION_ERROR", "patient_id 不能为空", status_code=400)
    try:
        patient_id = uuid.UUID(str(patient_id_str))
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    lifestyle_profile_id = None
    if lpid := body.get("lifestyle_profile_id"):
        try:
            lifestyle_profile_id = uuid.UUID(str(lpid))
        except ValueError:
            pass

    ta = await svc.generate_tcm_traits(
        db=db,
        patient_id=patient_id,
        lifestyle_profile_id=lifestyle_profile_id,
        symptom_items=body.get("symptom_items"),
        dialogue_text=body.get("dialogue_text"),
        encounter_id=body.get("encounter_id"),
        created_by=current_user.id,
    )
    await log_action(db, action="CREATE_TCM_ASSESSMENT", resource_type="TcmTraitAssessment",
                     user_id=current_user.id, resource_id=str(ta.id))
    await db.commit()
    return ok({"tcm_assessment_id": str(ta.id), **_ta_dict(ta)}, status_code=201)


@router.get("/tcm-assessments/{assessment_id}")
async def get_tcm_assessment(
    assessment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        aid = uuid.UUID(assessment_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "assessment_id 格式无效", status_code=400)
    ta = await db.get(TcmTraitAssessment, aid)
    if not ta:
        return fail("NOT_FOUND", "中医评估不存在", status_code=404)
    return ok(_ta_dict(ta))


# ══════════════════════════════════════════════════════════════════════════════
# § C  风险推断
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/risk-inferences")
async def create_risk_inference(
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """生成未来风险推断（AI 推断）。"""
    patient_id_str = body.get("patient_id")
    if not patient_id_str:
        return fail("VALIDATION_ERROR", "patient_id 不能为空", status_code=400)
    try:
        patient_id = uuid.UUID(str(patient_id_str))
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    lifestyle_profile_id = None
    if lpid := body.get("lifestyle_profile_id"):
        try:
            lifestyle_profile_id = uuid.UUID(str(lpid))
        except ValueError:
            pass

    ri = await svc.generate_future_risks(
        db=db,
        patient_id=patient_id,
        lifestyle_profile_id=lifestyle_profile_id,
        vitals=body.get("vitals"),
        encounter_id=body.get("encounter_id"),
        created_by=current_user.id,
    )
    await log_action(db, action="CREATE_RISK_INFERENCE", resource_type="RiskInference",
                     user_id=current_user.id, resource_id=str(ri.id))
    await db.commit()
    return ok({"risk_inference_id": str(ri.id), **_ri_dict(ri)}, status_code=201)


@router.get("/risk-inferences/{inference_id}")
async def get_risk_inference(
    inference_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        rid = uuid.UUID(inference_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "inference_id 格式无效", status_code=400)
    ri = await db.get(RiskInference, rid)
    if not ri:
        return fail("NOT_FOUND", "风险推断不存在", status_code=404)
    return ok(_ri_dict(ri))


# ══════════════════════════════════════════════════════════════════════════════
# § D  套餐推荐
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/packages/recommend")
async def recommend_packages(
    patient_id: str = Query(...),
    tcm_assessment_id: str | None = Query(default=None),
    risk_inference_id: str | None = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(_PRO_OR_ADMIN),
):
    """推荐适合患者的保健套餐。"""
    try:
        pid = uuid.UUID(patient_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    tid = None
    if tcm_assessment_id:
        try:
            tid = uuid.UUID(tcm_assessment_id)
        except ValueError:
            pass

    rid = None
    if risk_inference_id:
        try:
            rid = uuid.UUID(risk_inference_id)
        except ValueError:
            pass

    recommendations = await svc.recommend_packages(db, pid, tid, rid)
    return ok({"recommendations": recommendations, "total": len(recommendations)})


# ══════════════════════════════════════════════════════════════════════════════
# § E  方案 CRUD
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/plans")
async def create_plan(
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """新建方案草稿（整合四件套 + 套餐选择）。"""
    patient_id_str = body.get("patient_id")
    if not patient_id_str:
        return fail("VALIDATION_ERROR", "patient_id 不能为空", status_code=400)
    try:
        patient_id = uuid.UUID(str(patient_id_str))
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    def _opt_uuid(key: str) -> uuid.UUID | None:
        v = body.get(key)
        if not v:
            return None
        try:
            return uuid.UUID(str(v))
        except ValueError:
            return None

    plan = await svc.build_plan_draft(
        db=db,
        patient_id=patient_id,
        lifestyle_profile_id=_opt_uuid("lifestyle_profile_id"),
        tcm_assessment_id=_opt_uuid("tcm_assessment_id"),
        risk_inference_id=_opt_uuid("risk_inference_id"),
        selected_packages=body.get("selected_packages"),
        selected_items=body.get("selected_items"),
        doctor_note=body.get("doctor_note"),
        encounter_id=body.get("encounter_id"),
        created_by=current_user.id,
    )
    await log_action(db, action="CREATE_PREVENTIVE_PLAN", resource_type="PreventivePlan",
                     user_id=current_user.id, resource_id=str(plan.id))
    await db.commit()
    return ok({"plan_id": str(plan.id), "status": plan.status.value, "version": plan.version},
              status_code=201)


@router.get("/plans")
async def list_plans(
    patient_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """方案列表。"""
    filters = []
    if patient_id:
        try:
            filters.append(PreventivePlan.patient_id == uuid.UUID(patient_id))
        except ValueError:
            pass
    if status:
        try:
            filters.append(PreventivePlan.status == PreventivePlanStatus(status))
        except ValueError:
            pass

    stmt = (
        select(PreventivePlan)
        .where(and_(*filters) if filters else True)
        .order_by(desc(PreventivePlan.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    r = await db.execute(stmt)
    plans = r.scalars().all()
    return ok({"items": [_plan_dict(p) for p in plans], "page": page, "page_size": page_size})


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    plan = await db.get(PreventivePlan, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    return ok(_plan_dict(plan))


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """更新方案草稿（仅 DRAFT 状态可编辑）。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    plan = await db.get(PreventivePlan, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    if plan.status != PreventivePlanStatus.DRAFT:
        return fail("STATE_ERROR", f"方案状态 {plan.status.value} 不可编辑", status_code=409)

    editable = ["selected_packages", "selected_items", "doctor_note",
                 "patient_readable_note", "encounter_id"]
    for k in editable:
        if k in body:
            setattr(plan, k, body[k])

    # 重建经济选项
    if "selected_packages" in body:
        plan.economic_options = svc._build_economic_options(body["selected_packages"])

    db.add(plan)
    await db.commit()
    return ok({"plan_id": plan_id, "status": plan.status.value})


@router.get("/plans/{plan_id}/preview")
async def preview_plan(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    """获取方案完整预览（聚合四件套 + 套餐 + 经济选项 + 话术）。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    data = await svc.preview_plan(db, pid)
    if not data:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    return ok(data)


@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(
    plan_id: str,
    body: dict = Body(default={}),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """确认方案，版本锁定。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    try:
        doctor_id = uuid.UUID(str(body.get("doctor_id", ""))) if body.get("doctor_id") else current_user.id
    except ValueError:
        doctor_id = current_user.id

    try:
        plan = await svc.confirm_plan(db, pid, doctor_id)
    except ValueError as e:
        return fail("STATE_ERROR", str(e), status_code=409)

    await log_action(db, action="CONFIRM_PREVENTIVE_PLAN", resource_type="PreventivePlan",
                     user_id=current_user.id, resource_id=str(pid))
    await db.commit()
    return ok({"plan_id": str(plan.id), "status": plan.status.value,
                "confirmed_at": plan.confirmed_at.isoformat()})


@router.post("/plans/{plan_id}/distribute")
async def distribute_plan(
    plan_id: str,
    body: dict = Body(default={}),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """分发方案到各渠道（HIS/H5/ADMIN）。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)

    channel_raws = body.get("channels", ["H5", "ADMIN"])
    channels = []
    for ch in channel_raws:
        try:
            channels.append(DistributionChannel(ch))
        except ValueError:
            return fail("VALIDATION_ERROR", f"无效渠道: {ch}", status_code=400)

    his_mode = body.get("his_mode", "COPY")
    try:
        results = await svc.distribute_plan(db, pid, channels, his_mode)
    except ValueError as e:
        return fail("STATE_ERROR", str(e), status_code=409)

    await log_action(db, action="DISTRIBUTE_PREVENTIVE_PLAN", resource_type="PreventivePlan",
                     user_id=current_user.id, resource_id=str(pid),
                     new_values={"channels": channel_raws})
    await db.commit()
    return ok({"plan_id": plan_id, "results": results})


@router.post("/plans/{plan_id}/confirm-and-distribute")
async def confirm_and_distribute(
    plan_id: str,
    body: dict = Body(default={}),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """一步完成确认 + 分发。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)

    doctor_id = current_user.id
    if did := body.get("doctor_id"):
        try:
            doctor_id = uuid.UUID(str(did))
        except ValueError:
            pass

    try:
        plan = await svc.confirm_plan(db, pid, doctor_id)
    except ValueError as e:
        return fail("STATE_ERROR", str(e), status_code=409)

    channel_raws = body.get("channels", ["H5", "ADMIN"])
    channels = []
    for ch in channel_raws:
        try:
            channels.append(DistributionChannel(ch))
        except ValueError:
            return fail("VALIDATION_ERROR", f"无效渠道: {ch}", status_code=400)

    his_mode = body.get("his_mode", "COPY")
    results = await svc.distribute_plan(db, pid, channels, his_mode)

    await log_action(db, action="CONFIRM_AND_DISTRIBUTE_PLAN", resource_type="PreventivePlan",
                     user_id=current_user.id, resource_id=str(pid))
    await db.commit()
    return ok({
        "plan_id": str(plan.id),
        "status": plan.status.value,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "results": results,
    })


# ══════════════════════════════════════════════════════════════════════════════
# § F  随访任务
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/plans/{plan_id}/followups")
async def generate_followups(
    plan_id: str,
    body: dict = Body(default={}),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO_OR_ADMIN),
):
    """为方案自动生成随访任务（第7/14/28天 + 末次复诊）。"""
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    plan = await db.get(PreventivePlan, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)

    ruleset_days = body.get("ruleset_days")
    tasks = await svc.create_followups_from_plan(db, plan, ruleset_days)
    await log_action(db, action="GENERATE_FOLLOWUPS", resource_type="PreventivePlan",
                     user_id=current_user.id, resource_id=str(pid),
                     new_values={"task_count": len(tasks)})
    await db.commit()
    return ok({
        "plan_id": plan_id,
        "followup_task_ids": [str(t.id) for t in tasks],
        "count": len(tasks),
    }, status_code=201)


@router.get("/plans/{plan_id}/followups")
async def list_plan_followups(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "plan_id 格式无效", status_code=400)
    r = await db.execute(
        select(PreventiveFollowUpTask)
        .where(PreventiveFollowUpTask.plan_id == pid)
        .order_by(PreventiveFollowUpTask.due_at)
    )
    tasks = [_task_dict(t) for t in r.scalars().all()]
    return ok({"items": tasks, "total": len(tasks)})


@router.patch("/followups/{task_id}")
async def update_followup_task(
    task_id: str,
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """更新随访任务状态（患者/医生均可操作）。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "task_id 格式无效", status_code=400)
    task = await db.get(PreventiveFollowUpTask, tid)
    if not task:
        return fail("NOT_FOUND", "随访任务不存在", status_code=404)

    if status_raw := body.get("status"):
        try:
            task.status = PreventiveTaskStatus(status_raw)
        except ValueError:
            return fail("VALIDATION_ERROR", f"无效状态: {status_raw}", status_code=400)
    if "result_payload" in body:
        task.result_payload = body["result_payload"]

    db.add(task)
    await db.commit()
    return ok({"task_id": task_id, "status": task.status.value})


# ══════════════════════════════════════════════════════════════════════════════
# § G  意向/预约
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/intents")
async def create_intent(
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """创建患者意向或预约。"""
    patient_id_str = body.get("patient_id")
    if not patient_id_str:
        return fail("VALIDATION_ERROR", "patient_id 不能为空", status_code=400)
    try:
        patient_id = uuid.UUID(str(patient_id_str))
    except ValueError:
        return fail("VALIDATION_ERROR", "patient_id 格式无效", status_code=400)

    intent_type_raw = body.get("type", "APPOINTMENT")
    try:
        intent_type = IntentType(intent_type_raw)
    except ValueError:
        return fail("VALIDATION_ERROR", f"无效意向类型: {intent_type_raw}", status_code=400)

    plan_id = None
    if pid_str := body.get("plan_id"):
        try:
            plan_id = uuid.UUID(str(pid_str))
        except ValueError:
            pass

    scheduled_at = None
    if sat := body.get("scheduled_at"):
        try:
            scheduled_at = datetime.fromisoformat(str(sat))
        except ValueError:
            return fail("VALIDATION_ERROR", "scheduled_at 格式无效（ISO8601）", status_code=400)

    intent = await svc.create_intent(
        db=db,
        patient_id=patient_id,
        plan_id=plan_id,
        intent_type=intent_type,
        scheduled_at=scheduled_at,
        location=body.get("location"),
        contact=body.get("contact"),
        note=body.get("note"),
    )
    await db.commit()
    return ok({"intent_id": str(intent.id), "status": intent.status.value}, status_code=201)


@router.get("/intents")
async def list_intents(
    patient_id: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(get_current_user),
):
    filters = []
    if patient_id:
        try:
            filters.append(PatientIntent.patient_id == uuid.UUID(patient_id))
        except ValueError:
            pass
    if plan_id:
        try:
            filters.append(PatientIntent.plan_id == uuid.UUID(plan_id))
        except ValueError:
            pass
    if status:
        try:
            filters.append(PatientIntent.status == IntentStatus(status))
        except ValueError:
            pass

    r = await db.execute(
        select(PatientIntent)
        .where(and_(*filters) if filters else True)
        .order_by(desc(PatientIntent.created_at))
        .limit(50)
    )
    items = [_intent_dict(i) for i in r.scalars().all()]
    return ok({"items": items, "total": len(items)})


@router.patch("/intents/{intent_id}")
async def update_intent(
    intent_id: str,
    body: dict = Body(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(_PRO_OR_ADMIN),
):
    try:
        iid = uuid.UUID(intent_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "intent_id 格式无效", status_code=400)
    intent = await db.get(PatientIntent, iid)
    if not intent:
        return fail("NOT_FOUND", "意向不存在", status_code=404)

    if status_raw := body.get("status"):
        try:
            intent.status = IntentStatus(status_raw)
        except ValueError:
            return fail("VALIDATION_ERROR", f"无效状态: {status_raw}", status_code=400)

    editable = ["location", "contact", "note", "scheduled_at"]
    for k in editable:
        if k in body:
            val = body[k]
            if k == "scheduled_at" and val:
                try:
                    val = datetime.fromisoformat(str(val))
                except ValueError:
                    return fail("VALIDATION_ERROR", "scheduled_at 格式无效", status_code=400)
            setattr(intent, k, val)

    db.add(intent)
    await db.commit()
    return ok({"intent_id": intent_id, "status": intent.status.value})


# ══════════════════════════════════════════════════════════════════════════════
# § H  统计 KPI 快照
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/kpi")
async def kpi_snapshot(
    days: int = Query(default=30, ge=1, le=365),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    _=Depends(_PRO_OR_ADMIN),
):
    """管理端 KPI 快照：方案数、分发数、意向数。"""
    from sqlalchemy import func as sqlfunc, case
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)

    plan_r = await db.execute(
        select(
            sqlfunc.count(PreventivePlan.id).label("total"),
            sqlfunc.count(case((PreventivePlan.status == PreventivePlanStatus.CONFIRMED, 1))).label("confirmed"),
            sqlfunc.count(case((PreventivePlan.status == PreventivePlanStatus.DISTRIBUTED, 1))).label("distributed"),
        ).where(PreventivePlan.created_at >= since)
    )
    plan_row = plan_r.one()

    intent_r = await db.execute(
        select(sqlfunc.count(PatientIntent.id)).where(PatientIntent.created_at >= since)
    )
    intent_count = intent_r.scalar_one()

    return ok({
        "period_days": days,
        "plans": {"total": plan_row.total, "confirmed": plan_row.confirmed,
                   "distributed": plan_row.distributed},
        "intents": intent_count,
    })
