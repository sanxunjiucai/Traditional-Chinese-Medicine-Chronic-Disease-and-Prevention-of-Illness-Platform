"""
高中风险患者 Seed 脚本 —— 为 AI 风险分析流程提供完整演示数据。

每位患者数据完整：
  User 账号 → PatientArchive（user_id 关联）→ ChronicDiseaseRecord
  → ConstitutionAssessment → ClinicalDocument（LAB_REPORT，含异常指标）

运行方式：
    python scripts/seed_high_risk_patients.py

幂等：按 phone 去重，已存在则跳过。
"""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app.models  # noqa: F401
import app.models.org  # noqa: F401
import app.models.config  # noqa: F401
import app.models.clinical  # noqa: F401
import app.models.sysdict  # noqa: F401
import app.models.guidance  # noqa: F401

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, Base, engine
from app.models.archive import PatientArchive
from app.models.clinical import ClinicalDocument
from app.models.constitution import ConstitutionAssessment
from app.models.health import ChronicDiseaseRecord, HealthProfile
from app.models.user import User
from app.models.enums import (
    ArchiveType, AssessmentStatus, BodyType, DiseaseType,
    DocumentType, IdType, UserRole,
)
from app.services.auth_service import hash_password

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()

# ─────────────────────────────────────────────────────────────────────────────
# 患者定义：7名高/中风险患者，含异常检验指标
# ─────────────────────────────────────────────────────────────────────────────

HIGH_RISK_PATIENTS = [
    # ── 1. 老年高血压+糖尿病（高风险）────────────────────────────────────────
    {
        "phone": "13900001001",
        "name": "陈复明",
        "gender": "male",
        "birth_date": date(1958, 6, 12),
        "archive_type": ArchiveType.ELDERLY,
        "district": "朝阳区",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "lab_items": [
            {"name": "血糖（空腹）", "value": 9.8, "unit": "mmol/L", "flag": "HH",
             "reference_range": "3.9-6.1"},
            {"name": "糖化血红蛋白", "value": 9.2, "unit": "%", "flag": "HH",
             "reference_range": "4.0-6.0"},
            {"name": "总胆固醇", "value": 6.8, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.1-5.2"},
            {"name": "甘油三酯", "value": 3.4, "unit": "mmol/L", "flag": "H",
             "reference_range": "0.56-1.7"},
            {"name": "低密度脂蛋白", "value": 4.5, "unit": "mmol/L", "flag": "H",
             "reference_range": "0-3.37"},
            {"name": "肌酐", "value": 145, "unit": "μmol/L", "flag": "H",
             "reference_range": "44-133"},
        ],
        "dept": "内分泌科",
    },
    # ── 2. 老年女性高血压（高风险）──────────────────────────────────────────
    {
        "phone": "13900001002",
        "name": "刘桂英",
        "gender": "female",
        "birth_date": date(1955, 3, 28),
        "archive_type": ArchiveType.ELDERLY,
        "district": "海淀区",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.YIN_DEFICIENCY,
        "lab_items": [
            {"name": "血压（收缩压）", "value": 178, "unit": "mmHg", "flag": "HH",
             "reference_range": "90-140"},
            {"name": "血压（舒张压）", "value": 105, "unit": "mmHg", "flag": "H",
             "reference_range": "60-90"},
            {"name": "总胆固醇", "value": 6.2, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.1-5.2"},
            {"name": "低密度脂蛋白", "value": 4.1, "unit": "mmol/L", "flag": "H",
             "reference_range": "0-3.37"},
            {"name": "尿微量白蛋白", "value": 210, "unit": "mg/L", "flag": "HH",
             "reference_range": "0-30"},
        ],
        "dept": "心内科",
    },
    # ── 3. 中年男性代谢综合征（高风险）─────────────────────────────────────
    {
        "phone": "13900001003",
        "name": "赵建军",
        "gender": "male",
        "birth_date": date(1968, 11, 5),
        "archive_type": ArchiveType.KEY_FOCUS,
        "district": "丰台区",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.BLOOD_STASIS,
        "lab_items": [
            {"name": "血糖（空腹）", "value": 8.5, "unit": "mmol/L", "flag": "HH",
             "reference_range": "3.9-6.1"},
            {"name": "血压（收缩压）", "value": 162, "unit": "mmHg", "flag": "HH",
             "reference_range": "90-140"},
            {"name": "总胆固醇", "value": 7.1, "unit": "mmol/L", "flag": "HH",
             "reference_range": "3.1-5.2"},
            {"name": "甘油三酯", "value": 4.2, "unit": "mmol/L", "flag": "HH",
             "reference_range": "0.56-1.7"},
            {"name": "尿酸", "value": 520, "unit": "μmol/L", "flag": "H",
             "reference_range": "208-428"},
            {"name": "ALT（谷丙转氨酶）", "value": 85, "unit": "U/L", "flag": "H",
             "reference_range": "7-45"},
        ],
        "dept": "全科医学科",
    },
    # ── 4. 老年女性骨质疏松+高血压（中风险）────────────────────────────────
    {
        "phone": "13900001004",
        "name": "孙淑华",
        "gender": "female",
        "birth_date": date(1952, 8, 19),
        "archive_type": ArchiveType.ELDERLY,
        "district": "西城区",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.QI_DEFICIENCY,
        "lab_items": [
            {"name": "血压（收缩压）", "value": 155, "unit": "mmHg", "flag": "H",
             "reference_range": "90-140"},
            {"name": "血钙", "value": 1.9, "unit": "mmol/L", "flag": "L",
             "reference_range": "2.1-2.7"},
            {"name": "25-羟基维生素D", "value": 12, "unit": "ng/mL", "flag": "L",
             "reference_range": "20-100"},
            {"name": "碱性磷酸酶", "value": 152, "unit": "U/L", "flag": "H",
             "reference_range": "40-130"},
            {"name": "血红蛋白", "value": 98, "unit": "g/L", "flag": "L",
             "reference_range": "120-160"},
        ],
        "dept": "骨科",
    },
    # ── 5. 中年女性糖尿病前期（中风险）─────────────────────────────────────
    {
        "phone": "13900001005",
        "name": "王秀芳",
        "gender": "female",
        "birth_date": date(1972, 4, 16),
        "archive_type": ArchiveType.FEMALE,
        "district": "昌平区",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.DAMP_HEAT,
        "lab_items": [
            {"name": "血糖（空腹）", "value": 7.2, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.9-6.1"},
            {"name": "糖化血红蛋白", "value": 7.5, "unit": "%", "flag": "H",
             "reference_range": "4.0-6.0"},
            {"name": "总胆固醇", "value": 5.8, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.1-5.2"},
            {"name": "餐后2h血糖", "value": 11.8, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.9-7.8"},
        ],
        "dept": "内分泌科",
    },
    # ── 6. 老年男性慢性心衰（高风险）────────────────────────────────────────
    {
        "phone": "13900001006",
        "name": "张德贵",
        "gender": "male",
        "birth_date": date(1948, 2, 3),
        "archive_type": ArchiveType.ELDERLY,
        "district": "东城区",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.YANG_DEFICIENCY,
        "lab_items": [
            {"name": "NT-proBNP", "value": 2850, "unit": "pg/mL", "flag": "HH",
             "reference_range": "0-450"},
            {"name": "肌酐", "value": 168, "unit": "μmol/L", "flag": "HH",
             "reference_range": "44-133"},
            {"name": "钾", "value": 5.8, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.5-5.0"},
            {"name": "血红蛋白", "value": 95, "unit": "g/L", "flag": "L",
             "reference_range": "120-160"},
            {"name": "血压（收缩压）", "value": 170, "unit": "mmHg", "flag": "HH",
             "reference_range": "90-140"},
        ],
        "dept": "心内科",
    },
    # ── 7. 中年男性高尿酸+脂肪肝（中风险）──────────────────────────────────
    {
        "phone": "13900001007",
        "name": "李鸿飞",
        "gender": "male",
        "birth_date": date(1975, 9, 21),
        "archive_type": ArchiveType.KEY_FOCUS,
        "district": "顺义区",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "lab_items": [
            {"name": "尿酸", "value": 580, "unit": "μmol/L", "flag": "HH",
             "reference_range": "208-428"},
            {"name": "ALT（谷丙转氨酶）", "value": 125, "unit": "U/L", "flag": "HH",
             "reference_range": "7-45"},
            {"name": "AST（谷草转氨酶）", "value": 78, "unit": "U/L", "flag": "H",
             "reference_range": "13-40"},
            {"name": "甘油三酯", "value": 3.8, "unit": "mmol/L", "flag": "HH",
             "reference_range": "0.56-1.7"},
            {"name": "血糖（空腹）", "value": 6.5, "unit": "mmol/L", "flag": "H",
             "reference_range": "3.9-6.1"},
        ],
        "dept": "消化内科",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Seed 主函数
# ─────────────────────────────────────────────────────────────────────────────

async def seed(db: AsyncSession) -> None:
    created_count = 0
    skipped_count = 0

    for idx, p in enumerate(HIGH_RISK_PATIENTS):
        phone = p["phone"]

        # ── 幂等检查：User ──
        existing_user = (await db.execute(
            select(User).where(User.phone == phone)
        )).scalar_one_or_none()

        if existing_user:
            print(f"  [跳过] {p['name']}（{phone}）用户已存在")
            skipped_count += 1
            continue

        # ── 1. 创建 User ──
        user = User(
            phone=phone,
            name=p["name"],
            password_hash=hash_password("Demo@123456"),
            role=UserRole.PATIENT,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # ── 2. 创建 PatientArchive（关联 user_id）──
        archive = PatientArchive(
            user_id=user.id,
            name=p["name"],
            gender=p["gender"],
            birth_date=p["birth_date"],
            id_type=IdType.ID_CARD,
            phone=phone,
            archive_type=p["archive_type"],
            district=p["district"],
            city="北京市",
            province="北京市",
            past_history=["高血压病史"] if DiseaseType.HYPERTENSION in p["diseases"] else [],
            family_history=["父亲高血压"] if idx % 2 == 0 else [],
            allergy_history=[],
            is_deleted=False,
        )
        db.add(archive)
        await db.flush()

        # ── 3. 创建 HealthProfile ──
        profile = HealthProfile(
            user_id=user.id,
            gender=p["gender"],
            birth_date=p["birth_date"],
            height_cm=165 + idx * 2,
            weight_kg=70 + idx * 3,
            smoking="former" if idx % 3 == 0 else "never",
            drinking="occasional" if idx % 2 == 0 else "never",
            exercise_frequency="occasional",
            sleep_hours=6.5,
            stress_level="medium",
        )
        db.add(profile)

        # ── 4. 创建 ChronicDiseaseRecord ──
        for disease in p["diseases"]:
            record = ChronicDiseaseRecord(
                user_id=user.id,
                disease_type=disease,
                diagnosed_at=TODAY - timedelta(days=365 * (1 + idx % 3)),
                diagnosed_hospital="北京协和医院",
                is_active=True,
                notes=f"{p['name']} 已确诊，规律随访中",
            )
            db.add(record)

        # ── 5. 创建 ConstitutionAssessment ──
        assessment = ConstitutionAssessment(
            user_id=user.id,
            main_type=p["body_type"],
            secondary_types=[],
            result={p["body_type"].value: {"raw_score": 75 + idx * 2, "converted_score": 75 + idx * 2, "level": "yes"}},
            status=AssessmentStatus.SCORED,
            submitted_at=NOW - timedelta(days=30),
            scored_at=NOW - timedelta(days=30),
        )
        db.add(assessment)
        await db.flush()

        # ── 6. 创建 ClinicalDocument（LAB_REPORT）──
        lab_doc = ClinicalDocument(
            archive_id=archive.id,
            patient_name=p["name"],
            doc_type=DocumentType.LAB_REPORT,
            source_system="LIS",
            dept=p["dept"],
            doc_date=NOW - timedelta(days=7 + idx * 3),
            content={
                "report_title": "常规检验报告",
                "items": p["lab_items"],
            },
            sync_mode="MANUAL",
        )
        db.add(lab_doc)

        print(f"  [新增] {p['name']}（{phone}）user_id={user.id}, archive_id={archive.id}")
        created_count += 1

    await db.commit()
    print(f"\n完成：新增 {created_count} 名高中风险患者，跳过 {skipped_count} 名已有记录。")


async def main() -> None:
    # 确保表已创建
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
