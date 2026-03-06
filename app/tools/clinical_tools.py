"""
临床数据查询 API（HIS/LIS/PACS/设备 对接 - 演示模式使用 mock 数据）
GET /tools/clinical/documents  通用查询
GET /tools/clinical/documents/{id} 详情
POST /tools/clinical/sync  手动同步触发（演示：生成mock数据）
GET /tools/clinical/sync/logs  同步日志
"""
import uuid
import random
from datetime import datetime, timedelta, UTC
from typing import Any

from fastapi import APIRouter, Body, Cookie, Query
from sqlalchemy import select, func

from app.database import AsyncSessionLocal
from app.models.clinical import ClinicalDocument, SyncLog
from app.models.enums import DocumentType
from app.services.auth_service import decode_token
from app.tools.response import ok, fail as err

router = APIRouter(prefix="/clinical", tags=["clinical"])


def _auth(access_token: str | None) -> dict | None:
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    if payload.get("role") not in ("ADMIN", "PROFESSIONAL"):
        return None
    return payload


# ── 文档列表 ──────────────────────────────────────────────────────────
@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    doc_type: str | None = None,
    archive_id: str | None = None,
    patient_name: str | None = None,
    dept: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        stmt = select(ClinicalDocument)
        if doc_type:
            stmt = stmt.where(ClinicalDocument.doc_type == doc_type)
        if archive_id:
            try:
                stmt = stmt.where(ClinicalDocument.archive_id == uuid.UUID(archive_id))
            except ValueError:
                pass
        elif patient_name:
            stmt = stmt.where(ClinicalDocument.patient_name.ilike(f"%{patient_name}%"))
        if dept:
            stmt = stmt.where(ClinicalDocument.dept.ilike(f"%{dept}%"))
        if date_from:
            try:
                stmt = stmt.where(ClinicalDocument.doc_date >= datetime.fromisoformat(date_from))
            except Exception:
                pass
        if date_to:
            try:
                stmt = stmt.where(ClinicalDocument.doc_date <= datetime.fromisoformat(date_to))
            except Exception:
                pass

        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.order_by(ClinicalDocument.doc_date.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()

        items = [{
            "id": str(r.id),
            "doc_type": r.doc_type,
            "patient_name": r.patient_name,
            "dept": r.dept,
            "doctor": r.doctor,
            "doc_date": r.doc_date.isoformat() if r.doc_date else None,
            "external_ref_no": r.external_ref_no,
            "source_system": r.source_system,
            "sync_mode": r.sync_mode,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        } for r in rows]
        return ok({"total": total, "items": items})


# ── 文档详情 ──────────────────────────────────────────────────────────
@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        try:
            did = uuid.UUID(doc_id)
        except ValueError:
            return err("INVALID_ID", "无效ID")
        row = await sess.get(ClinicalDocument, did)
        if not row:
            return err("NOT_FOUND", "文档不存在")
        return ok({
            "id": str(row.id),
            "doc_type": row.doc_type,
            "patient_name": row.patient_name,
            "archive_id": str(row.archive_id) if row.archive_id else None,
            "dept": row.dept,
            "doctor": row.doctor,
            "doc_date": row.doc_date.isoformat() if row.doc_date else None,
            "external_ref_no": row.external_ref_no,
            "encounter_ref": row.encounter_ref,
            "source_system": row.source_system,
            "sync_mode": row.sync_mode,
            "sync_batch": row.sync_batch,
            "content": row.content,
            "created_at": row.created_at.isoformat(),
        })


# ── 手动同步（演示：生成 mock 数据）────────────────────────────────
@router.post("/sync")
async def trigger_sync(body: dict, access_token: str | None = Cookie(default=None)):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录")

    sync_type = body.get("sync_type", "HIS_ENCOUNTER")
    count = random.randint(5, 20)
    started = datetime.now(UTC)

    async with AsyncSessionLocal() as sess:
        docs = _generate_mock_docs(sync_type, count)
        for d in docs:
            sess.add(d)

        log = SyncLog(
            sync_type=sync_type,
            trigger_mode="MANUAL",
            status="SUCCESS",
            total_count=count,
            success_count=count,
            fail_count=0,
            operator_id=_parse_uuid(payload.get("sub")),
            started_at=started,
            finished_at=datetime.now(UTC),
        )
        sess.add(log)
        await sess.commit()
        return ok({"sync_type": sync_type, "total": count, "success": count, "fail": 0})


# ── 同步日志 ──────────────────────────────────────────────────────────
@router.get("/sync/logs")
async def list_sync_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        stmt = select(SyncLog).order_by(SyncLog.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id),
            "sync_type": r.sync_type,
            "trigger_mode": r.trigger_mode,
            "status": r.status,
            "total_count": r.total_count,
            "success_count": r.success_count,
            "fail_count": r.fail_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat(),
        } for r in rows]
        return ok({"total": total, "items": items})


# ── 统计概览 ──────────────────────────────────────────────────────────
@router.get("/stats")
async def clinical_stats(access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        by_type: dict[str, int] = {}
        for dt in DocumentType:
            cnt = await sess.scalar(
                select(func.count(ClinicalDocument.id)).where(ClinicalDocument.doc_type == dt)
            )
            by_type[dt.value] = cnt or 0
        total = sum(by_type.values())
        last_sync = await sess.scalar(
            select(func.max(SyncLog.finished_at))
        )
        return ok({
            "total": total,
            "by_type": by_type,
            "last_sync_at": last_sync.isoformat() if last_sync else None,
        })


# ── mock data generator ───────────────────────────────────────────────
MOCK_NAMES = ["张三", "李四", "王五", "赵六", "陈七", "刘八", "孙九", "周十"]
MOCK_DEPTS = ["心内科", "内分泌科", "中医科", "老年科", "全科诊室", "门诊部"]
MOCK_DOCTORS = ["张医生", "李医生", "王医生", "赵医生", "陈医生"]

_TYPE_SYSTEM_MAP = {
    "HIS_ENCOUNTER": ("ENCOUNTER", "HIS"),
    "HIS_OP_EMR": ("OP_EMR", "HIS"),
    "HIS_IP_EMR": ("IP_EMR", "HIS"),
    "HIS_PRESCRIPTION": ("PRESCRIPTION", "HIS"),
    "HIS_TREATMENT": ("TREATMENT", "HIS"),
    "LIS_LAB": ("LAB_REPORT", "LIS"),
    "PACS_IMAGE": ("IMAGE_REPORT", "PACS"),
    "DEVICE_REPORT": ("DEVICE_REPORT", "DEVICE"),
}


def _generate_mock_docs(sync_type: str, count: int) -> list[ClinicalDocument]:
    doc_type_str, source = _TYPE_SYSTEM_MAP.get(sync_type, ("ENCOUNTER", "HIS"))
    docs = []
    for i in range(count):
        base_date = datetime.now(UTC) - timedelta(days=random.randint(1, 180))
        content = _mock_content(doc_type_str, i)
        doc = ClinicalDocument(
            patient_name=random.choice(MOCK_NAMES),
            doc_type=doc_type_str,
            source_system=source,
            external_ref_no=f"{source}-{uuid.uuid4().hex[:8].upper()}",
            encounter_ref=f"V{uuid.uuid4().hex[:6].upper()}",
            dept=random.choice(MOCK_DEPTS),
            doctor=random.choice(MOCK_DOCTORS),
            doc_date=base_date,
            content=content,
            sync_mode="MANUAL",
            sync_batch=f"BATCH-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        )
        docs.append(doc)
    return docs


def _mock_content(doc_type: str, idx: int) -> dict:
    if doc_type == "ENCOUNTER":
        return {"encounter_type": random.choice(["门诊", "住院", "急诊"]),
                "chief_complaint": "头痛、失眠数日", "diagnosis": "高血压"}
    elif doc_type == "OP_EMR":
        return {"chief_complaint": "头晕、乏力", "present_illness": "患者自述头晕乏力2周",
                "physical_exam": "血压150/90mmHg", "diagnosis": "高血压2级", "plan": "降压治疗"}
    elif doc_type == "IP_EMR":
        return {"admission_chief_complaint": "胸闷气短", "admission_diagnosis": "冠心病",
                "discharge_diagnosis": "冠心病稳定型", "hospital_days": random.randint(3, 14)}
    elif doc_type == "PRESCRIPTION":
        drugs = [{"name": "苯磺酸氨氯地平片", "dose": "5mg", "freq": "每日一次", "days": 30},
                 {"name": "复方丹参片", "dose": "3片", "freq": "每日三次", "days": 15}]
        return {"drugs": random.sample(drugs, 1)}
    elif doc_type == "TREATMENT":
        return {"treatment_name": random.choice(["针灸治疗", "推拿治疗", "中药熏蒸"]),
                "times": random.randint(1, 10), "executor": "技师王"}
    elif doc_type == "LAB_REPORT":
        items = [
            {"item_code": "FBG", "item_name": "空腹血糖", "value": f"{random.uniform(4.5, 9.0):.1f}",
             "unit": "mmol/L", "ref_range": "3.9-6.1", "abnormal_flag": "H" if random.random() > 0.7 else "N"},
            {"item_code": "HbA1c", "item_name": "糖化血红蛋白", "value": f"{random.uniform(5.5, 9.5):.1f}",
             "unit": "%", "ref_range": "4.0-6.5", "abnormal_flag": "H" if random.random() > 0.6 else "N"},
        ]
        return {"items": items, "report_conclusion": "部分指标偏高，建议复查"}
    elif doc_type == "IMAGE_REPORT":
        return {"exam_part": random.choice(["胸部", "头颅", "腹部"]),
                "findings": "双肺纹理清晰，未见明显异常", "impression": "正常范围",
                "image_url": None}
    elif doc_type == "DEVICE_REPORT":
        return {"device_type": random.choice(["心电图仪", "血压计", "血糖仪"]),
                "device_no": f"DEV{idx:04d}",
                "indicators": [{"name": "血压", "value": f"{random.randint(110,160)}/{random.randint(70,100)}",
                                "unit": "mmHg"}],
                "conclusion": "血压偏高，建议就医"}
    return {}


def _parse_uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None
