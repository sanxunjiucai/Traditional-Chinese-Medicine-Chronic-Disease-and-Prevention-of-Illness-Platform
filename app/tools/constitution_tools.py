from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.constitution import ConstitutionAnswer, ConstitutionAssessment, ConstitutionQuestion
from app.models.enums import AssessmentStatus, DiseaseType, PlanStatus
from app.models.health import ChronicDiseaseRecord
from app.models.recommendation import RecommendationPlan
from app.models.user import User
from app.services.audit_service import log_action
from app.services.constitution_scorer import score_assessment
from app.services.recommendation_engine import generate_plan
from app.tools.response import fail, ok

router = APIRouter(prefix="/constitution", tags=["constitution-tools"])


@router.post("/start")
async def start_assessment(
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    import uuid as _uuid
    from app.models.archive import PatientArchive

    # 管理端代患者创建：传入 archive_id 时，解析出对应患者的 user_id
    target_user_id = current_user.id
    archive_id_raw = body.get("archive_id")
    if archive_id_raw:
        try:
            arc_uuid = _uuid.UUID(str(archive_id_raw))
        except ValueError:
            return fail("VALIDATION_ERROR", "archive_id 格式错误", status_code=400)
        arc_r = await db.execute(
            select(PatientArchive).where(PatientArchive.id == arc_uuid)
        )
        arc = arc_r.scalar_one_or_none()
        if arc is None:
            return fail("NOT_FOUND", "患者档案不存在", status_code=404)
        if arc.user_id is None:
            return fail("VALIDATION_ERROR", "该患者档案尚未关联系统账号，无法创建评估", status_code=400)
        target_user_id = arc.user_id

    # 如果已有 ANSWERING 状态的评估，直接返回
    existing_result = await db.execute(
        select(ConstitutionAssessment).where(
            and_(
                ConstitutionAssessment.user_id == target_user_id,
                ConstitutionAssessment.status == AssessmentStatus.ANSWERING,
            )
        ).limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return ok({"assessment_id": str(existing.id), "resumed": True})

    assessment = ConstitutionAssessment(
        user_id=target_user_id,
        status=AssessmentStatus.ANSWERING,
    )
    db.add(assessment)
    await db.flush()
    await log_action(
        db, action="START_ASSESSMENT", resource_type="ConstitutionAssessment",
        user_id=current_user.id, resource_id=str(assessment.id),
    )
    await db.commit()
    return ok({"assessment_id": str(assessment.id), "resumed": False}, status_code=201)


class AnswerItem(BaseModel):
    question_id: str
    answer_value: int  # 1-5


class AnswerRequest(BaseModel):
    assessment_id: str
    answers: list[AnswerItem]


@router.post("/answer")
async def save_answers(
    body: AnswerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    import uuid
    from app.models.enums import UserRole
    is_proxy = current_user.role in (UserRole.ADMIN, UserRole.PROFESSIONAL)
    filters = [ConstitutionAssessment.id == uuid.UUID(body.assessment_id)]
    if not is_proxy:
        filters.append(ConstitutionAssessment.user_id == current_user.id)
    assessment_result = await db.execute(
        select(ConstitutionAssessment).where(and_(*filters))
    )
    assessment = assessment_result.scalar_one_or_none()
    if assessment is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)
    if assessment.status != AssessmentStatus.ANSWERING:
        return fail("STATE_ERROR", "评估已提交，无法修改答案", status_code=409)

    for item in body.answers:
        q_id = uuid.UUID(item.question_id)
        existing_ans_result = await db.execute(
            select(ConstitutionAnswer).where(
                and_(
                    ConstitutionAnswer.assessment_id == assessment.id,
                    ConstitutionAnswer.question_id == q_id,
                )
            )
        )
        ans = existing_ans_result.scalar_one_or_none()
        if ans:
            ans.answer_value = item.answer_value
            db.add(ans)
        else:
            ans = ConstitutionAnswer(
                assessment_id=assessment.id,
                question_id=q_id,
                answer_value=item.answer_value,
            )
            db.add(ans)

    await db.commit()
    return ok({"saved": len(body.answers)})


@router.post("/submit")
async def submit_assessment(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    import uuid
    from app.models.enums import UserRole
    assessment_id = uuid.UUID(body.get("assessment_id", ""))
    is_proxy = current_user.role in (UserRole.ADMIN, UserRole.PROFESSIONAL)
    filters = [ConstitutionAssessment.id == assessment_id]
    if not is_proxy:
        filters.append(ConstitutionAssessment.user_id == current_user.id)
    assessment_result = await db.execute(
        select(ConstitutionAssessment).where(and_(*filters))
    )
    assessment = assessment_result.scalar_one_or_none()
    if assessment is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)
    if assessment.status not in (AssessmentStatus.ANSWERING, AssessmentStatus.SUBMITTED):
        return fail("STATE_ERROR", "评估已评分，无法重新提交", status_code=409)

    # 加载所有答案和对应题目信息
    answers_result = await db.execute(
        select(ConstitutionAnswer, ConstitutionQuestion)
        .join(ConstitutionQuestion, ConstitutionAnswer.question_id == ConstitutionQuestion.id)
        .where(ConstitutionAnswer.assessment_id == assessment_id)
    )
    rows = answers_result.all()

    if not rows:
        return fail("VALIDATION_ERROR", "请先填写问卷答案", status_code=400)

    answer_dicts = [
        {
            "question_id": str(ans.question_id),
            "answer_value": ans.answer_value,
            "body_type": q.body_type.value,
            "is_reverse": q.is_reverse,
        }
        for ans, q in rows
    ]

    # 评分
    assessment.status = AssessmentStatus.SUBMITTED
    assessment.submitted_at = datetime.now(timezone.utc)

    result = score_assessment(answer_dicts)

    assessment.main_type = result.main_type
    assessment.secondary_types = [bt.value for bt in result.secondary_types]
    assessment.result = {
        k: {
            "raw_score": v.raw_score,
            "converted_score": v.converted_score,
            "level": v.level,
            "name": v.name,
        }
        for k, v in result.scores.items()
    }
    assessment.status = AssessmentStatus.REPORTED
    assessment.scored_at = datetime.now(timezone.utc)
    db.add(assessment)

    await db.flush()

    # 获取用户病种（用于调护建议匹配）
    disease_result = await db.execute(
        select(ChronicDiseaseRecord).where(
            and_(
                ChronicDiseaseRecord.user_id == current_user.id,
                ChronicDiseaseRecord.is_active == True,  # noqa: E712
            )
        )
    )
    diseases = disease_result.scalars().all()
    disease_types = [d.disease_type for d in diseases]

    # 生成调护建议方案
    plan = await generate_plan(
        db=db,
        user_id=current_user.id,
        main_type=result.main_type,
        disease_types=disease_types if disease_types else None,
        assessment_id=assessment.id,
    )

    await log_action(
        db, action="SUBMIT_ASSESSMENT", resource_type="ConstitutionAssessment",
        user_id=current_user.id, resource_id=str(assessment.id),
        new_values={"main_type": result.main_type.value},
    )
    await db.commit()

    return ok({
        "assessment_id": str(assessment.id),
        "main_type": result.main_type.value,
        "secondary_types": [bt.value for bt in result.secondary_types],
        "recommendation_plan_id": str(plan.id),
        "scores": {k: v.converted_score for k, v in result.scores.items()},
    })


@router.get("/questions")
async def list_questions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(ConstitutionQuestion)
        .where(ConstitutionQuestion.is_active == True)  # noqa: E712
        .order_by(ConstitutionQuestion.body_type, ConstitutionQuestion.seq)
    )
    questions = result.scalars().all()
    return ok([
        {
            "id": str(q.id),
            "code": q.code,
            "body_type": q.body_type.value,
            "seq": q.seq,
            "content": q.content,
            "options": q.options,
            "is_reverse": q.is_reverse,
        }
        for q in questions
    ])


@router.get("/latest")
async def latest_assessment(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(ConstitutionAssessment)
        .where(
            and_(
                ConstitutionAssessment.user_id == current_user.id,
                ConstitutionAssessment.status == AssessmentStatus.REPORTED,
            )
        )
        .order_by(ConstitutionAssessment.scored_at.desc())
        .limit(1)
    )
    assessment = result.scalar_one_or_none()
    if assessment is None:
        return ok(None)
    return ok({
        "id": str(assessment.id),
        "main_type": assessment.main_type.value if assessment.main_type else None,
        "secondary_types": assessment.secondary_types,
        "result": assessment.result,
        "scored_at": assessment.scored_at.isoformat() if assessment.scored_at else None,
    })


@router.get("/recommendation")
async def get_recommendation(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    """获取当前用户最新的活跃调护建议方案。"""
    result = await db.execute(
        select(RecommendationPlan)
        .where(
            and_(
                RecommendationPlan.user_id == current_user.id,
                RecommendationPlan.status == PlanStatus.ACTIVE,
            )
        )
        .order_by(RecommendationPlan.created_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return ok(None)
    return ok({
        "id": str(plan.id),
        "version": plan.version,
        "items": plan.items,
        "note": plan.note,
        "created_at": plan.created_at.isoformat(),
    })


# ══════════════════════════════════════════════
# 体质评估详情 & 报告（管理端）
# ══════════════════════════════════════════════

@router.get("/assessments/{assess_id}")
async def get_assessment_detail(
    assess_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    """体质评估详情（管理端/患者端共用）。"""
    import uuid as _uuid
    try:
        aid = _uuid.UUID(assess_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "assess_id 格式错误", status_code=400)

    a_result = await db.execute(
        select(ConstitutionAssessment).where(ConstitutionAssessment.id == aid)
    )
    assessment = a_result.scalar_one_or_none()
    if assessment is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)

    user_r = await db.execute(select(User).where(User.id == assessment.user_id))
    user = user_r.scalar_one_or_none()
    patient_name = user.name if user else "未知患者"

    result_data = assessment.result or {}
    scores = {
        bt: v.get("converted_score", 0)
        for bt, v in result_data.items()
        if isinstance(v, dict) and not bt.startswith("_")
    }
    report = result_data.get("_report")

    plan_r = await db.execute(
        select(RecommendationPlan)
        .where(
            and_(
                RecommendationPlan.user_id == assessment.user_id,
                RecommendationPlan.assessment_id == assessment.id,
            )
        )
        .limit(1)
    )
    plan = plan_r.scalar_one_or_none()
    recommendations = []
    if plan:
        recommendations = [
            {"content": item.get("content", item.get("title", ""))}
            for item in (plan.items or [])[:5]
        ]

    return ok({
        "id": str(assessment.id),
        "patient_name": patient_name,
        "status": assessment.status.value,
        "primary_body_type": assessment.main_type.value if assessment.main_type else None,
        "secondary_body_types": assessment.secondary_types or [],
        "scores": scores,
        "recommendations": recommendations,
        "report": report,
        "created_at": assessment.created_at.isoformat(),
        "scored_at": assessment.scored_at.isoformat() if assessment.scored_at else None,
    })


@router.patch("/assessments/{assess_id}/report")
async def update_assessment_report(
    assess_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    """保存体质评估报告内容（存储在 result['_report']）。"""
    import uuid as _uuid
    try:
        aid = _uuid.UUID(assess_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "assess_id 格式错误", status_code=400)

    a_result = await db.execute(
        select(ConstitutionAssessment).where(ConstitutionAssessment.id == aid)
    )
    assessment = a_result.scalar_one_or_none()
    if assessment is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)

    result_data = dict(assessment.result or {})
    result_data["_report"] = {
        "conclusion": body.get("conclusion", ""),
        "recommendations": body.get("recommendations", {}),
        "audit_status": body.get("audit_status", ""),
        "audit_comment": body.get("audit_comment", ""),
        "report_status": body.get("report_status", "DRAFT"),
    }
    assessment.result = result_data

    report_status = body.get("report_status")
    if report_status == "APPROVED":
        assessment.status = AssessmentStatus.REPORTED
    elif report_status == "PENDING_REVIEW":
        assessment.status = AssessmentStatus.SUBMITTED

    await db.commit()
    return ok({"id": str(assessment.id)})
