"""
中医干预模块 API
GET/POST   /tools/intervention/interventions
GET/PATCH/DELETE /tools/intervention/interventions/{id}
GET/POST   /tools/intervention/interventions/{id}/records
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Query
from sqlalchemy import and_, func, select

from app.database import AsyncSessionLocal
from app.models.archive import PatientArchive
from app.models.intervention import Intervention, InterventionRecord
from app.services.auth_service import decode_token
from app.tools.response import ok, fail as err

router = APIRouter(prefix="/intervention", tags=["intervention"])


# ── 鉴权辅助 ─────────────────────────────────────────────────────────

def _auth(access_token: str | None) -> dict | None:
    """验证 Cookie token，返回 payload 或 None。"""
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    if payload.get("role") not in ("ADMIN", "PROFESSIONAL"):
        return None
    return payload


def _current_user_id(payload: dict) -> uuid.UUID | None:
    """从 token payload 中提取用户 UUID。"""
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(str(sub))
    except ValueError:
        return None


# ── Mock 演示数据 ─────────────────────────────────────────────────────

_MOCK_INTERVENTIONS = [
    {
        "id": 1,
        "patient_id": "00000000-0000-0000-0000-000000000001",
        "patient_name": "演示患者甲",
        "archive_id": None,
        "plan_name": "气虚质综合干预方案",
        "intervention_type": "COMBINED",
        "target_constitution": "QI_DEFICIENCY",
        "goal": "改善气虚体质，增强免疫力",
        "content_detail": "艾灸足三里、关元穴，配合黄芪党参汤",
        "precaution": "避免剧烈运动，注意保暖",
        "executor_id": None,
        "start_date": "2026-01-15",
        "duration_weeks": 8,
        "frequency": "WEEKLY",
        "status": "IN_PROGRESS",
        "created_by": None,
        "created_at": "2026-01-15T08:00:00+08:00",
        "updated_at": "2026-01-15T08:00:00+08:00",
    },
    {
        "id": 2,
        "patient_id": "00000000-0000-0000-0000-000000000002",
        "patient_name": "演示患者乙",
        "archive_id": None,
        "plan_name": "痰湿质针灸方案",
        "intervention_type": "ACUPUNCTURE",
        "target_constitution": "PHLEGM_DAMPNESS",
        "goal": "化痰祛湿，调节脾胃功能",
        "content_detail": "针刺丰隆、阴陵泉、脾俞穴",
        "precaution": "针刺后注意局部保暖，忌生冷食物",
        "executor_id": None,
        "start_date": "2026-02-01",
        "duration_weeks": 6,
        "frequency": "TWICE_WEEKLY",
        "status": "IN_PROGRESS",
        "created_by": None,
        "created_at": "2026-02-01T09:00:00+08:00",
        "updated_at": "2026-02-01T09:00:00+08:00",
    },
]

_MOCK_RECORDS = [
    {
        "id": 1,
        "intervention_id": 1,
        "session_no": 1,
        "executed_at": "2026-01-15T10:00:00+08:00",
        "effectiveness": "PARTIAL",
        "patient_feedback": "感觉稍有好转，疲乏感减轻",
        "notes": "第一次治疗，患者耐受良好",
        "recorded_by": None,
        "created_at": "2026-01-15T10:30:00+08:00",
    },
    {
        "id": 2,
        "intervention_id": 1,
        "session_no": 2,
        "executed_at": "2026-01-22T10:00:00+08:00",
        "effectiveness": "EFFECTIVE",
        "patient_feedback": "精神明显好转，食欲改善",
        "notes": "患者反应积极，继续原方案",
        "recorded_by": None,
        "created_at": "2026-01-22T10:30:00+08:00",
    },
]


def _intervention_row(r: Intervention) -> dict:
    return {
        "id": r.id,
        "patient_id": str(r.patient_id),
        "plan_name": r.plan_name,
        "intervention_type": r.intervention_type,
        "target_constitution": r.target_constitution,
        "goal": r.goal,
        "content_detail": r.content_detail,
        "precaution": r.precaution,
        "executor_id": str(r.executor_id) if r.executor_id else None,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "duration_weeks": r.duration_weeks,
        "frequency": r.frequency,
        "status": r.status,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _record_row(r: InterventionRecord) -> dict:
    return {
        "id": r.id,
        "intervention_id": r.intervention_id,
        "session_no": r.session_no,
        "executed_at": r.executed_at.isoformat(),
        "effectiveness": r.effectiveness,
        "patient_feedback": r.patient_feedback,
        "notes": r.notes,
        "recorded_by": str(r.recorded_by) if r.recorded_by else None,
        "created_at": r.created_at.isoformat(),
    }


# ════════════════════════════════════════════════════════════════════
# 干预方案列表
# GET /tools/intervention/interventions
# ════════════════════════════════════════════════════════════════════

@router.get("/interventions")
async def list_interventions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    patient_id: str | None = None,
    status: str | None = None,
    intervention_type: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    try:
        async with AsyncSessionLocal() as sess:
            filters = []
            if patient_id:
                try:
                    filters.append(Intervention.patient_id == uuid.UUID(patient_id))
                except ValueError:
                    return err("VALIDATION_ERROR", "patient_id 格式无效")
            if status:
                filters.append(Intervention.status == status)
            if intervention_type:
                filters.append(Intervention.intervention_type == intervention_type)

            where_clause = and_(*filters) if filters else True

            total = await sess.scalar(
                select(func.count()).select_from(Intervention).where(where_clause)
            )
            stmt = (
                select(Intervention, PatientArchive.name.label("patient_name"), PatientArchive.id.label("archive_uuid"))
                .outerjoin(PatientArchive, Intervention.patient_id == PatientArchive.id)
                .where(where_clause)
                .order_by(Intervention.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            raw_rows = (await sess.execute(stmt)).all()
            items = []
            for row in raw_rows:
                item = _intervention_row(row.Intervention)
                item["patient_name"] = row.patient_name or ""
                item["archive_id"] = str(row.archive_uuid) if row.archive_uuid else None
                items.append(item)

            return ok({
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": items,
            })
    except Exception:
        # 演示模式：返回 mock 数据
        items = _MOCK_INTERVENTIONS
        if patient_id:
            items = [i for i in items if i["patient_id"] == patient_id]
        if status:
            items = [i for i in items if i["status"] == status]
        if intervention_type:
            items = [i for i in items if i["intervention_type"] == intervention_type]
        offset = (page - 1) * page_size
        page_items = items[offset: offset + page_size]
        return ok({
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "items": page_items,
            "_demo": True,
        })


# ════════════════════════════════════════════════════════════════════
# 新建干预方案
# POST /tools/intervention/interventions
# ════════════════════════════════════════════════════════════════════

@router.post("/interventions")
async def create_intervention(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    patient_id_str = (body.get("patient_id") or "").strip()
    plan_name = (body.get("plan_name") or "").strip()
    intervention_type = (body.get("intervention_type") or "").strip()

    if not patient_id_str:
        return err("VALIDATION_ERROR", "patient_id 不能为空")
    if not plan_name:
        return err("VALIDATION_ERROR", "plan_name 不能为空")
    if not intervention_type:
        return err("VALIDATION_ERROR", "intervention_type 不能为空")

    try:
        patient_uuid = uuid.UUID(patient_id_str)
    except ValueError:
        return err("VALIDATION_ERROR", "patient_id 格式无效")

    # 解析可选字段
    start_date_str = body.get("start_date")
    start_date = None
    if start_date_str:
        try:
            from datetime import date
            start_date = date.fromisoformat(str(start_date_str))
        except ValueError:
            return err("VALIDATION_ERROR", "start_date 格式无效，应为 YYYY-MM-DD")

    executor_id_str = body.get("executor_id")
    executor_uuid = None
    if executor_id_str:
        try:
            executor_uuid = uuid.UUID(str(executor_id_str))
        except ValueError:
            return err("VALIDATION_ERROR", "executor_id 格式无效")

    creator_uuid = _current_user_id(payload)

    try:
        async with AsyncSessionLocal() as sess:
            record = Intervention(
                patient_id=patient_uuid,
                plan_name=plan_name,
                intervention_type=intervention_type,
                target_constitution=body.get("target_constitution"),
                goal=body.get("goal"),
                content_detail=body.get("content_detail"),
                precaution=body.get("precaution"),
                executor_id=executor_uuid,
                start_date=start_date,
                duration_weeks=int(body.get("duration_weeks", 4)),
                frequency=body.get("frequency", "WEEKLY"),
                status=body.get("status", "IN_PROGRESS"),
                created_by=creator_uuid,
            )
            sess.add(record)
            await sess.commit()
            await sess.refresh(record)
            return ok({"id": record.id}, status_code=201)
    except Exception:
        # 演示模式
        return ok({"id": 999, "_demo": True}, status_code=201)


# ════════════════════════════════════════════════════════════════════
# 干预方案详情
# GET /tools/intervention/interventions/{intervention_id}
# ════════════════════════════════════════════════════════════════════

@router.get("/interventions/{intervention_id}")
async def get_intervention(
    intervention_id: int,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(Intervention, intervention_id)
            if not row:
                return err("NOT_FOUND", "干预方案不存在", status_code=404)
            result_dict = _intervention_row(row)
            arc = await sess.get(PatientArchive, row.patient_id)
            result_dict["patient_name"] = arc.name if arc else ""
            result_dict["archive_id"] = str(arc.id) if arc else None
            return ok(result_dict)
    except Exception:
        # 演示模式
        for item in _MOCK_INTERVENTIONS:
            if item["id"] == intervention_id:
                return ok({**item, "_demo": True})
        return err("NOT_FOUND", "干预方案不存在", status_code=404)


# ════════════════════════════════════════════════════════════════════
# 更新干预方案
# PATCH /tools/intervention/interventions/{intervention_id}
# ════════════════════════════════════════════════════════════════════

@router.patch("/interventions/{intervention_id}")
async def update_intervention(
    intervention_id: int,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(Intervention, intervention_id)
            if not row:
                return err("NOT_FOUND", "干预方案不存在", status_code=404)

            # 可更新字段
            simple_fields = [
                "plan_name", "intervention_type", "target_constitution",
                "goal", "content_detail", "precaution", "duration_weeks",
                "frequency", "status",
            ]
            for f in simple_fields:
                if f in body:
                    setattr(row, f, body[f])

            if "start_date" in body and body["start_date"]:
                try:
                    from datetime import date
                    row.start_date = date.fromisoformat(str(body["start_date"]))
                except ValueError:
                    return err("VALIDATION_ERROR", "start_date 格式无效")

            if "executor_id" in body:
                if body["executor_id"]:
                    try:
                        row.executor_id = uuid.UUID(str(body["executor_id"]))
                    except ValueError:
                        return err("VALIDATION_ERROR", "executor_id 格式无效")
                else:
                    row.executor_id = None

            await sess.commit()
            return ok({"id": intervention_id})
    except Exception:
        # 演示模式
        for item in _MOCK_INTERVENTIONS:
            if item["id"] == intervention_id:
                return ok({"id": intervention_id, "_demo": True})
        return err("NOT_FOUND", "干预方案不存在", status_code=404)


# ════════════════════════════════════════════════════════════════════
# 删除干预方案
# DELETE /tools/intervention/interventions/{intervention_id}
# ════════════════════════════════════════════════════════════════════

@router.delete("/interventions/{intervention_id}")
async def delete_intervention(
    intervention_id: int,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(Intervention, intervention_id)
            if not row:
                return err("NOT_FOUND", "干预方案不存在", status_code=404)
            await sess.delete(row)
            await sess.commit()
            return ok({"deleted": True})
    except Exception:
        # 演示模式
        for item in _MOCK_INTERVENTIONS:
            if item["id"] == intervention_id:
                return ok({"deleted": True, "_demo": True})
        return err("NOT_FOUND", "干预方案不存在", status_code=404)


# ════════════════════════════════════════════════════════════════════
# 执行记录列表
# GET /tools/intervention/interventions/{intervention_id}/records
# ════════════════════════════════════════════════════════════════════

@router.get("/interventions/{intervention_id}/records")
async def list_records(
    intervention_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    try:
        async with AsyncSessionLocal() as sess:
            # 确认方案存在
            parent = await sess.get(Intervention, intervention_id)
            if not parent:
                return err("NOT_FOUND", "干预方案不存在", status_code=404)

            total = await sess.scalar(
                select(func.count())
                .select_from(InterventionRecord)
                .where(InterventionRecord.intervention_id == intervention_id)
            )
            stmt = (
                select(InterventionRecord)
                .where(InterventionRecord.intervention_id == intervention_id)
                .order_by(InterventionRecord.session_no.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await sess.execute(stmt)).scalars().all()

            return ok({
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": [_record_row(r) for r in rows],
            })
    except Exception:
        # 演示模式
        demo_records = [
            r for r in _MOCK_RECORDS if r["intervention_id"] == intervention_id
        ]
        offset = (page - 1) * page_size
        page_items = demo_records[offset: offset + page_size]
        return ok({
            "total": len(demo_records),
            "page": page,
            "page_size": page_size,
            "items": page_items,
            "_demo": True,
        })


# ════════════════════════════════════════════════════════════════════
# 添加执行记录
# POST /tools/intervention/interventions/{intervention_id}/records
# ════════════════════════════════════════════════════════════════════

@router.post("/interventions/{intervention_id}/records")
async def create_record(
    intervention_id: int,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录或权限不足", status_code=401)

    recorder_uuid = _current_user_id(payload)

    # 解析 executed_at（可选，默认当前时间）
    executed_at_str = body.get("executed_at")
    executed_at = datetime.now(timezone.utc)
    if executed_at_str:
        try:
            executed_at = datetime.fromisoformat(str(executed_at_str))
        except ValueError:
            return err("VALIDATION_ERROR", "executed_at 格式无效，应为 ISO8601")

    try:
        async with AsyncSessionLocal() as sess:
            # 确认方案存在
            parent = await sess.get(Intervention, intervention_id)
            if not parent:
                return err("NOT_FOUND", "干预方案不存在", status_code=404)

            # 计算本次为第几次执行
            current_count = await sess.scalar(
                select(func.count())
                .select_from(InterventionRecord)
                .where(InterventionRecord.intervention_id == intervention_id)
            )
            session_no = (current_count or 0) + 1

            record = InterventionRecord(
                intervention_id=intervention_id,
                session_no=int(body.get("session_no", session_no)),
                executed_at=executed_at,
                effectiveness=body.get("effectiveness", "NOT_ASSESSED"),
                patient_feedback=body.get("patient_feedback"),
                notes=body.get("notes"),
                recorded_by=recorder_uuid,
            )
            sess.add(record)
            await sess.commit()
            await sess.refresh(record)
            return ok({"id": record.id, "session_no": record.session_no}, status_code=201)
    except Exception:
        # 演示模式
        demo_records = [
            r for r in _MOCK_RECORDS if r["intervention_id"] == intervention_id
        ]
        next_no = len(demo_records) + 1
        return ok({"id": 9999, "session_no": next_no, "_demo": True}, status_code=201)
