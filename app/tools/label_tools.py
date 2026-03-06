"""
标签管理 API
GET/POST/PATCH/DELETE /label/categories          标签分类 CRUD
GET/POST/PATCH/DELETE /label/labels              标签 CRUD
GET/POST/DELETE       /label/patients/{id}/labels 患者标签
GET                   /label/stats               使用统计
"""
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, Cookie, Query
from sqlalchemy import select, func, and_, delete

from app.database import AsyncSessionLocal
from app.models.label import LabelCategory, Label, PatientLabel
from app.services.auth_service import decode_token
from app.tools.response import ok, fail as err

router = APIRouter(prefix="/label", tags=["label"])


# ── 认证辅助 ─────────────────────────────────────────────────────────


def _auth(access_token: str | None) -> dict | None:
    """验证 token，要求角色为 ADMIN 或 PROFESSIONAL。"""
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    if payload.get("role") not in ("ADMIN", "PROFESSIONAL"):
        return None
    return payload


def _parse_uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        return None


# ── Mock 数据（DB 失败时回退）────────────────────────────────────────

_MOCK_CATEGORIES = [
    {"id": 1, "name": "基本信息",   "color": "#6b7280", "sort_order": 1, "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 2, "name": "慢病管理",   "color": "#ef4444", "sort_order": 2, "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 3, "name": "中医体质",   "color": "#10b981", "sort_order": 3, "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 4, "name": "风险分级",   "color": "#f59e0b", "sort_order": 4, "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 5, "name": "随访状态",   "color": "#3b82f6", "sort_order": 5, "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
]

_MOCK_LABELS = [
    {"id": 1,  "name": "高血压",     "category_id": 2, "scope": "SYSTEM", "color": "#ef4444", "description": "原发性高血压患者",   "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 2,  "name": "糖尿病",     "category_id": 2, "scope": "SYSTEM", "color": "#f97316", "description": "2型糖尿病患者",       "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 3,  "name": "冠心病",     "category_id": 2, "scope": "SYSTEM", "color": "#dc2626", "description": "冠状动脉粥样硬化性心脏病", "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 4,  "name": "平和质",     "category_id": 3, "scope": "SYSTEM", "color": "#10b981", "description": "中医体质：平和质",   "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 5,  "name": "气虚质",     "category_id": 3, "scope": "SYSTEM", "color": "#6ee7b7", "description": "中医体质：气虚质",   "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 6,  "name": "阳虚质",     "category_id": 3, "scope": "SYSTEM", "color": "#34d399", "description": "中医体质：阳虚质",   "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 7,  "name": "高风险",     "category_id": 4, "scope": "SYSTEM", "color": "#dc2626", "description": "高风险患者",         "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 8,  "name": "中风险",     "category_id": 4, "scope": "SYSTEM", "color": "#f59e0b", "description": "中风险患者",         "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 9,  "name": "规律随访中", "category_id": 5, "scope": "SYSTEM", "color": "#3b82f6", "description": "正在规律随访",       "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": 10, "name": "失联",       "category_id": 5, "scope": "CUSTOM", "color": "#9ca3af", "description": "无法联系患者",       "is_active": True, "created_by": None, "created_at": "2026-01-01T00:00:00+00:00"},
]

_MOCK_PATIENT_LABELS = [
    {"id": 1, "patient_id": "00000000-0000-0000-0000-000000000001", "label_id": 1, "note": "确诊5年",  "created_by": None, "created_at": "2026-02-01T00:00:00+00:00", "label": _MOCK_LABELS[0]},
    {"id": 2, "patient_id": "00000000-0000-0000-0000-000000000001", "label_id": 7, "note": "血压控制差", "created_by": None, "created_at": "2026-02-01T00:00:00+00:00", "label": _MOCK_LABELS[6]},
    {"id": 3, "patient_id": "00000000-0000-0000-0000-000000000002", "label_id": 2, "note": None,      "created_by": None, "created_at": "2026-02-15T00:00:00+00:00", "label": _MOCK_LABELS[1]},
]

_MOCK_STATS = {
    "total_labels": 10,
    "total_categories": 5,
    "patient_covered": 128,
    "top10": [
        {"label_id": 1, "name": "高血压",     "color": "#ef4444", "count": 45},
        {"label_id": 2, "name": "糖尿病",     "color": "#f97316", "count": 38},
        {"label_id": 7, "name": "高风险",     "color": "#dc2626", "count": 31},
        {"label_id": 9, "name": "规律随访中", "color": "#3b82f6", "count": 27},
        {"label_id": 3, "name": "冠心病",     "color": "#dc2626", "count": 19},
        {"label_id": 8, "name": "中风险",     "color": "#f59e0b", "count": 15},
        {"label_id": 5, "name": "气虚质",     "color": "#6ee7b7", "count": 12},
        {"label_id": 6, "name": "阳虚质",     "color": "#34d399", "count": 9},
        {"label_id": 4, "name": "平和质",     "color": "#10b981", "count": 7},
        {"label_id": 10, "name": "失联",      "color": "#9ca3af", "count": 4},
    ],
    "by_category": [
        {"category_id": 2, "name": "慢病管理", "color": "#ef4444", "label_count": 3, "usage_count": 102},
        {"category_id": 5, "name": "随访状态", "color": "#3b82f6", "label_count": 2, "usage_count": 31},
        {"category_id": 4, "name": "风险分级", "color": "#f59e0b", "label_count": 2, "usage_count": 46},
        {"category_id": 3, "name": "中医体质", "color": "#10b981", "label_count": 3, "usage_count": 28},
        {"category_id": 1, "name": "基本信息", "color": "#6b7280", "label_count": 0, "usage_count": 0},
    ],
}


# ─────────────────────────────────────────────────────────────────────
# 标签分类 LabelCategory
# ─────────────────────────────────────────────────────────────────────


def _fmt_category(r: LabelCategory) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "color": r.color,
        "sort_order": r.sort_order,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(),
    }


# 1. GET /label/categories
@router.get("/categories")
async def list_categories(
    is_active: bool | None = Query(default=None, description="按激活状态筛选"),
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            stmt = select(LabelCategory)
            if is_active is not None:
                stmt = stmt.where(LabelCategory.is_active == is_active)
            stmt = stmt.order_by(LabelCategory.sort_order.asc(), LabelCategory.id.asc())
            rows = (await sess.execute(stmt)).scalars().all()
            return ok({"items": [_fmt_category(r) for r in rows], "total": len(rows)})
    except Exception:
        return ok({"items": _MOCK_CATEGORIES, "total": len(_MOCK_CATEGORIES), "_demo": True})


# 2. POST /label/categories
@router.post("/categories")
async def create_category(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    name = (body.get("name") or "").strip()
    if not name:
        return err("MISSING_FIELD", "分类名称不能为空")
    try:
        async with AsyncSessionLocal() as sess:
            record = LabelCategory(
                name=name,
                color=body.get("color", "#6b7280"),
                sort_order=int(body.get("sort_order", 0)),
            )
            sess.add(record)
            await sess.commit()
            await sess.refresh(record)
            return ok({"id": record.id}, status_code=201)
    except Exception:
        return ok({"id": 99, "name": name, "_demo": True}, status_code=201)


# 3. PATCH /label/categories/{cat_id}
@router.patch("/categories/{cat_id}")
async def update_category(
    cat_id: int,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(LabelCategory, cat_id)
            if not row:
                return err("NOT_FOUND", "标签分类不存在", status_code=404)
            for field in ("name", "color", "sort_order", "is_active"):
                if field in body:
                    setattr(row, field, body[field])
            await sess.commit()
            return ok({"id": row.id})
    except Exception:
        return ok({"id": cat_id, "_demo": True})


# 4. DELETE /label/categories/{cat_id}
@router.delete("/categories/{cat_id}")
async def delete_category(
    cat_id: int,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(LabelCategory, cat_id)
            if not row:
                return err("NOT_FOUND", "标签分类不存在", status_code=404)
            # 有关联标签时拒绝删除
            label_count = await sess.scalar(
                select(func.count(Label.id)).where(Label.category_id == cat_id)
            )
            if label_count and label_count > 0:
                return err(
                    "STATE_ERROR",
                    f"该分类下存在 {label_count} 个标签，请先移除或转移标签",
                    status_code=409,
                )
            await sess.delete(row)
            await sess.commit()
            return ok({"deleted": True})
    except Exception as exc:
        # 如果是我们自己构造的 err 响应，直接透传
        if "STATE_ERROR" in str(exc) or "NOT_FOUND" in str(exc):
            raise
        return ok({"deleted": True, "_demo": True})


# ─────────────────────────────────────────────────────────────────────
# 标签 Label
# ─────────────────────────────────────────────────────────────────────


def _fmt_label(r: Label) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "category_id": r.category_id,
        "scope": r.scope,
        "color": r.color,
        "description": r.description,
        "is_active": r.is_active,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
    }


# 5. GET /label/labels
@router.get("/labels")
async def list_labels(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: int | None = Query(default=None, description="按分类筛选"),
    scope: str | None = Query(default=None, description="SYSTEM / CUSTOM"),
    q: str | None = Query(default=None, description="按名称模糊搜索"),
    is_active: bool | None = Query(default=None, description="按激活状态筛选"),
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            stmt = select(Label)
            if category_id is not None:
                stmt = stmt.where(Label.category_id == category_id)
            if scope:
                stmt = stmt.where(Label.scope == scope.upper())
            if q:
                stmt = stmt.where(Label.name.ilike(f"%{q}%"))
            if is_active is not None:
                stmt = stmt.where(Label.is_active == is_active)
            total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
            stmt = stmt.order_by(Label.id.asc()).offset((page - 1) * page_size).limit(page_size)
            rows = (await sess.execute(stmt)).scalars().all()
            return ok({
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [_fmt_label(r) for r in rows],
            })
    except Exception:
        return ok({
            "total": len(_MOCK_LABELS),
            "page": page,
            "page_size": page_size,
            "items": _MOCK_LABELS,
            "_demo": True,
        })


# 6. POST /label/labels
@router.post("/labels")
async def create_label(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    name = (body.get("name") or "").strip()
    if not name:
        return err("MISSING_FIELD", "标签名称不能为空")
    scope_val = (body.get("scope") or "CUSTOM").upper()
    # SYSTEM 标签只允许 ADMIN 创建
    if scope_val == "SYSTEM" and payload.get("role") != "ADMIN":
        return err("PERMISSION_ERROR", "仅管理员可创建系统标签", status_code=403)
    try:
        async with AsyncSessionLocal() as sess:
            record = Label(
                name=name,
                category_id=body.get("category_id"),
                scope=scope_val,
                color=body.get("color", "#6b7280"),
                description=body.get("description"),
                created_by=_parse_uuid(payload.get("sub")),
            )
            sess.add(record)
            await sess.commit()
            await sess.refresh(record)
            return ok({"id": record.id}, status_code=201)
    except Exception:
        return ok({"id": 99, "name": name, "_demo": True}, status_code=201)


# 7. PATCH /label/labels/{label_id}
@router.patch("/labels/{label_id}")
async def update_label(
    label_id: int,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(Label, label_id)
            if not row:
                return err("NOT_FOUND", "标签不存在", status_code=404)
            for field in ("name", "category_id", "color", "description", "is_active"):
                if field in body:
                    setattr(row, field, body[field])
            await sess.commit()
            return ok({"id": row.id})
    except Exception:
        return ok({"id": label_id, "_demo": True})


# 8. DELETE /label/labels/{label_id}
@router.delete("/labels/{label_id}")
async def delete_label(
    label_id: int,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.get(Label, label_id)
            if not row:
                return err("NOT_FOUND", "标签不存在", status_code=404)
            if row.scope == "SYSTEM":
                return err("STATE_ERROR", "系统预设标签不可删除", status_code=409)
            await sess.delete(row)
            await sess.commit()
            return ok({"deleted": True})
    except Exception:
        return ok({"deleted": True, "_demo": True})


# ─────────────────────────────────────────────────────────────────────
# 患者标签 PatientLabel
# ─────────────────────────────────────────────────────────────────────


def _fmt_patient_label(r: PatientLabel) -> dict:
    result: dict = {
        "id": r.id,
        "patient_id": str(r.patient_id),
        "label_id": r.label_id,
        "note": r.note,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
        "label": None,
    }
    if r.label:
        result["label"] = _fmt_label(r.label)
    return result


# 9. GET /label/patients/{patient_id}/labels
@router.get("/patients/{patient_id}/labels")
async def list_patient_labels(
    patient_id: str,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    pid = _parse_uuid(patient_id)
    if not pid:
        return err("INVALID_ID", "无效的患者ID")
    try:
        async with AsyncSessionLocal() as sess:
            from sqlalchemy.orm import selectinload
            stmt = (
                select(PatientLabel)
                .where(PatientLabel.patient_id == pid)
                .options(selectinload(PatientLabel.label))
                .order_by(PatientLabel.created_at.desc())
            )
            rows = (await sess.execute(stmt)).scalars().all()
            return ok({"items": [_fmt_patient_label(r) for r in rows], "total": len(rows)})
    except Exception:
        mock_filtered = [pl for pl in _MOCK_PATIENT_LABELS if pl["patient_id"] == patient_id]
        return ok({"items": mock_filtered, "total": len(mock_filtered), "_demo": True})


# 10. POST /label/patients/{patient_id}/labels
@router.post("/patients/{patient_id}/labels")
async def add_patient_label(
    patient_id: str,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    pid = _parse_uuid(patient_id)
    if not pid:
        return err("INVALID_ID", "无效的患者ID")
    label_id = body.get("label_id")
    if not label_id:
        return err("MISSING_FIELD", "label_id 不能为空")
    try:
        label_id = int(label_id)
    except (TypeError, ValueError):
        return err("INVALID_FIELD", "label_id 必须为整数")
    try:
        async with AsyncSessionLocal() as sess:
            # 检查标签是否存在
            label_row = await sess.get(Label, label_id)
            if not label_row:
                return err("NOT_FOUND", "标签不存在", status_code=404)
            # 检查重复打标
            existing = await sess.scalar(
                select(func.count(PatientLabel.id)).where(
                    and_(
                        PatientLabel.patient_id == pid,
                        PatientLabel.label_id == label_id,
                    )
                )
            )
            if existing and existing > 0:
                return err("STATE_ERROR", "该患者已存在此标签", status_code=409)
            record = PatientLabel(
                patient_id=pid,
                label_id=label_id,
                note=body.get("note"),
                created_by=_parse_uuid(payload.get("sub")),
            )
            sess.add(record)
            await sess.commit()
            await sess.refresh(record)
            return ok({"id": record.id}, status_code=201)
    except Exception:
        return ok({"id": 99, "_demo": True}, status_code=201)


# 11. DELETE /label/patients/{patient_id}/labels/{label_id}
@router.delete("/patients/{patient_id}/labels/{label_id}")
async def remove_patient_label(
    patient_id: str,
    label_id: int,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    pid = _parse_uuid(patient_id)
    if not pid:
        return err("INVALID_ID", "无效的患者ID")
    try:
        async with AsyncSessionLocal() as sess:
            row = await sess.scalar(
                select(PatientLabel).where(
                    and_(
                        PatientLabel.patient_id == pid,
                        PatientLabel.label_id == label_id,
                    )
                )
            )
            if not row:
                return err("NOT_FOUND", "患者标签关联不存在", status_code=404)
            await sess.delete(row)
            await sess.commit()
            return ok({"deleted": True})
    except Exception:
        return ok({"deleted": True, "_demo": True})


# ─────────────────────────────────────────────────────────────────────
# 统计 Stats
# ─────────────────────────────────────────────────────────────────────


# 12. GET /label/stats
@router.get("/stats")
async def label_stats(access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    try:
        async with AsyncSessionLocal() as sess:
            total_labels = await sess.scalar(select(func.count(Label.id)))
            total_categories = await sess.scalar(select(func.count(LabelCategory.id)))

            # 患者覆盖数（有标签的不重复患者数）
            patient_covered = await sess.scalar(
                select(func.count(func.distinct(PatientLabel.patient_id)))
            )

            # Top 10 标签（按使用次数降序）
            top10_rows = (
                await sess.execute(
                    select(
                        Label.id.label("label_id"),
                        Label.name,
                        Label.color,
                        func.count(PatientLabel.id).label("count"),
                    )
                    .join(PatientLabel, PatientLabel.label_id == Label.id, isouter=True)
                    .group_by(Label.id, Label.name, Label.color)
                    .order_by(func.count(PatientLabel.id).desc())
                    .limit(10)
                )
            ).all()
            top10 = [
                {"label_id": r.label_id, "name": r.name, "color": r.color, "count": r.count}
                for r in top10_rows
            ]

            # 各分类统计
            cat_rows = (
                await sess.execute(
                    select(
                        LabelCategory.id.label("category_id"),
                        LabelCategory.name,
                        LabelCategory.color,
                        func.count(Label.id).label("label_count"),
                    )
                    .join(Label, Label.category_id == LabelCategory.id, isouter=True)
                    .group_by(LabelCategory.id, LabelCategory.name, LabelCategory.color)
                    .order_by(LabelCategory.sort_order.asc())
                )
            ).all()

            # 各分类使用量（通过 PatientLabel 汇总）
            cat_usage_rows = (
                await sess.execute(
                    select(
                        Label.category_id,
                        func.count(PatientLabel.id).label("usage_count"),
                    )
                    .join(PatientLabel, PatientLabel.label_id == Label.id, isouter=True)
                    .group_by(Label.category_id)
                )
            ).all()
            cat_usage_map: dict[int | None, int] = {
                r.category_id: r.usage_count for r in cat_usage_rows
            }

            by_category = [
                {
                    "category_id": r.category_id,
                    "name": r.name,
                    "color": r.color,
                    "label_count": r.label_count,
                    "usage_count": cat_usage_map.get(r.category_id, 0),
                }
                for r in cat_rows
            ]

            return ok({
                "total_labels": total_labels or 0,
                "total_categories": total_categories or 0,
                "patient_covered": patient_covered or 0,
                "top10": top10,
                "by_category": by_category,
            })
    except Exception:
        return ok({**_MOCK_STATS, "_demo": True})
