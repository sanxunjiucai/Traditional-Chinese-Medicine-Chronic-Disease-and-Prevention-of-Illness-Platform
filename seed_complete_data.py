"""完整演示数据填充脚本"""
import asyncio
import uuid
from datetime import datetime, timedelta, UTC
from app.database import AsyncSessionLocal
from app.models.archive import PatientArchive
from app.models.constitution import ConstitutionAssessment
from app.models.followup import FollowupPlan, FollowupRecord
from app.models.education import EducationRecord
from app.models.scale import Scale, ScaleRecord
from sqlalchemy import select, func

async def seed_all():
    async with AsyncSessionLocal() as sess:
        # 1. 获取现有患者
        stmt = select(PatientArchive).where(PatientArchive.is_deleted == False).limit(10)
        patients = (await sess.execute(stmt)).scalars().all()

        if len(patients) < 10:
            print("患者数据不足，请先运行 seed_rich_demo.py")
            return

        print(f"✓ 找到 {len(patients)} 个患者")

        # 2. 补充体质评估数据
        for i, patient in enumerate(patients[:8]):
            existing = await sess.scalar(
                select(func.count(ConstitutionAssessment.id))
                .where(ConstitutionAssessment.patient_id == patient.id)
            )
            if existing == 0:
                assessment = ConstitutionAssessment(
                    patient_id=patient.id,
                    assessment_date=datetime.now(UTC) - timedelta(days=30+i*5),
                    primary_type=["平和质", "气虚质", "阳虚质", "阴虚质", "痰湿质"][i % 5],
                    primary_score=75 + i * 2,
                    secondary_types=["气虚质", "阳虚质"] if i % 3 == 0 else [],
                    scores={"平和质": 75, "气虚质": 60, "阳虚质": 45},
                    recommendations="建议调理气血，适当运动",
                    status="COMPLETED"
                )
                sess.add(assessment)

        await sess.commit()
        print("✓ 已补充体质评估数据")

        # 3. 添加随访记录
        plans = (await sess.execute(
            select(FollowupPlan).limit(5)
        )).scalars().all()

        for plan in plans:
            existing = await sess.scalar(
                select(func.count(FollowupRecord.id))
                .where(FollowupRecord.plan_id == plan.id)
            )
            if existing == 0:
                for i in range(2):
                    record = FollowupRecord(
                        plan_id=plan.id,
                        patient_id=plan.patient_id,
                        scheduled_date=datetime.now(UTC) - timedelta(days=15*i),
                        actual_date=datetime.now(UTC) - timedelta(days=15*i),
                        status="COMPLETED",
                        blood_pressure="130/85",
                        blood_sugar="6.2",
                        symptoms="无明显不适",
                        notes="患者状态良好，继续观察"
                    )
                    sess.add(record)

        await sess.commit()
        print("✓ 已添加随访记录")

        # 4. 添加宣教记录
        for i, patient in enumerate(patients[:6]):
            record = EducationRecord(
                patient_id=patient.id,
                title=["高血压健康教育", "糖尿病饮食指导", "中医养生知识", "运动康复指导"][i % 4],
                content="详细的健康教育内容...",
                category=["CHRONIC_DISEASE", "TCM_HEALTH", "NUTRITION", "EXERCISE"][i % 4],
                delivery_method="FACE_TO_FACE",
                duration_minutes=30,
                educator_id=None,
                education_date=datetime.now(UTC) - timedelta(days=10+i*3),
                feedback="患者理解良好",
                effectiveness="GOOD"
            )
            sess.add(record)

        await sess.commit()
        print("✓ 已添加宣教记录")

        # 5. 添加量表记录
        scales = (await sess.execute(select(Scale).limit(2))).scalars().all()

        for i, patient in enumerate(patients[:4]):
            if scales:
                scale = scales[i % len(scales)]
                record = ScaleRecord(
                    patient_id=patient.id,
                    scale_id=scale.id,
                    assessment_date=datetime.now(UTC) - timedelta(days=20+i*5),
                    answers={"q1": "A", "q2": "B", "q3": "C"},
                    total_score=15 + i * 3,
                    completed_at=datetime.now(UTC) - timedelta(days=20+i*5),
                    conclusion="评估结果正常"
                )
                sess.add(record)

        await sess.commit()
        print("✓ 已添加量表记录")

        print("\n数据填充完成！")

if __name__ == "__main__":
    asyncio.run(seed_all())
