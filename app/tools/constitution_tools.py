from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.constitution import ConstitutionAnswer, ConstitutionAssessment, ConstitutionQuestion
from app.models.enums import AssessmentStatus, DiseaseType
from app.models.health import ChronicDiseaseRecord
from app.services.audit_service import log_action
from app.services.constitution_scorer import score_assessment
from app.services.recommendation_engine import generate_plan
from app.tools.response import fail, ok

router = APIRouter(prefix="/constitution", tags=["constitution-tools"])


@router.post("/start")
async def start_assessment(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    # 如果已有 ANSWERING 状态的评估，直接返回
    existing_result = await db.execute(
        select(ConstitutionAssessment).where(
            and_(
                ConstitutionAssessment.user_id == current_user.id,
                ConstitutionAssessment.status == AssessmentStatus.ANSWERING,
            )
        ).limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return ok({"assessment_id": str(existing.id), "resumed": True})

    assessment = ConstitutionAssessment(
        user_id=current_user.id,
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
    assessment_result = await db.execute(
        select(ConstitutionAssessment).where(
            and_(
                ConstitutionAssessment.id == uuid.UUID(body.assessment_id),
                ConstitutionAssessment.user_id == current_user.id,
            )
        )
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
    assessment_id = uuid.UUID(body.get("assessment_id", ""))
    assessment_result = await db.execute(
        select(ConstitutionAssessment).where(
            and_(
                ConstitutionAssessment.id == assessment_id,
                ConstitutionAssessment.user_id == current_user.id,
            )
        )
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
