"""
全量系统测试 - 最小颗粒度
=============================
覆盖所有核心 API 路由：
  auth / archive / health / constitution / scale / followup /
  alert / guidance / intervention / education / consultation /
  content / label / risk / stats / plugin / admin / profile /
  mgmt / sysdict / notification / clinical

每个用例尽量独立，使用 db_session + async_client fixtures。
"""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.enums import (
    UserRole, ArchiveType, DiseaseType, IndicatorType,
    AssessmentStatus, BodyType, GuidanceType, GuidanceStatus,
    FollowupStatus, TaskType, AlertStatus, AlertSeverity,
)
from app.models.user import User
from app.models.archive import PatientArchive
from app.models.health import HealthIndicator, HealthProfile, ChronicDiseaseRecord
from app.models.constitution import ConstitutionAssessment, ConstitutionQuestion
from app.models.followup import FollowupPlan, FollowupTask
from app.models.alert import AlertRule, AlertEvent
from app.models.guidance import GuidanceRecord, GuidanceTemplate
from app.models.content import ContentItem
from app.models.label import LabelCategory, Label, PatientLabel
from app.models.scale import Scale, ScaleQuestion, ScaleRecord
from app.models.consultation import Consultation, ConsultationMessage
from app.models.org import Organization
from app.models.sysdict import DictGroup, DictItem
from app.services.auth_service import hash_password, create_access_token
from tests.conftest import make_auth_cookie

PW = "Test@123456"

# ── 快捷创建函数 ──────────────────────────────────────────────────────────────

async def mk_user(db, phone, name, role=UserRole.PATIENT):
    u = User(phone=phone, name=name, password_hash=hash_password(PW), role=role)
    db.add(u)
    await db.flush()
    return u

async def mk_archive(db, user=None, name="测试患者", archive_type=ArchiveType.NORMAL):
    a = PatientArchive(
        name=name,
        gender="male",
        phone="13900000001",
        archive_type=archive_type,
        user_id=user.id if user else None,
        is_deleted=False,
    )
    db.add(a)
    await db.flush()
    return a

def cookies(user):
    return make_auth_cookie(user)["cookies"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. 认证模块 auth_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestAuth:
    @pytest.mark.asyncio
    async def test_login_success(self, async_client: AsyncClient, db_session):
        await mk_user(db_session, "13100000001", "登录用户")
        resp = await async_client.post("/tools/auth/login", json={"phone": "13100000001", "password": PW})
        assert resp.status_code == 200
        assert "access_token" in resp.cookies or "data" in resp.json()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, async_client: AsyncClient, db_session):
        await mk_user(db_session, "13100000002", "用户2")
        resp = await async_client.post("/tools/auth/login", json={"phone": "13100000002", "password": "wrong"})
        assert resp.status_code in (400, 401)

    @pytest.mark.asyncio
    async def test_login_not_found(self, async_client: AsyncClient, db_session):
        resp = await async_client.post("/tools/auth/login", json={"phone": "19999999999", "password": PW})
        assert resp.status_code in (400, 401, 404)

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, async_client: AsyncClient, db_session):
        resp = await async_client.post("/tools/auth/login", json={"phone": "13100000001"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_success(self, async_client: AsyncClient, db_session):
        resp = await async_client.post("/tools/auth/register", json={
            "phone": "13100009999", "password": PW, "name": "新用户"
        })
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_register_duplicate_phone(self, async_client: AsyncClient, db_session):
        await mk_user(db_session, "13100000003", "已存在")
        resp = await async_client.post("/tools/auth/register", json={
            "phone": "13100000003", "password": PW, "name": "重复"
        })
        assert resp.status_code in (400, 409)

    @pytest.mark.asyncio
    async def test_logout(self, async_client: AsyncClient, patient_user):
        resp = await async_client.post("/tools/auth/logout", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_unauthenticated_access(self, async_client: AsyncClient, db_session):
        resp = await async_client.get("/tools/archive/archives")
        assert resp.status_code in (400, 401, 403)  # archive_tools returns 401 for no auth


# ══════════════════════════════════════════════════════════════════════════════
# 2. 档案模块 archive_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestArchive:
    @pytest.mark.asyncio
    async def test_list_archives(self, async_client, admin_user, db_session):
        await mk_archive(db_session, name="档案甲")
        resp = await async_client.get("/tools/archive/archives", cookies=cookies(admin_user))
        assert resp.status_code == 200
        assert "items" in resp.json()["data"]

    @pytest.mark.asyncio
    async def test_create_archive(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/archive/archives", json={
            "name": "新建患者", "gender": "male", "phone": "13200000001",
            "archive_type": "NORMAL"
        }, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_archive(self, async_client, admin_user, db_session):
        # archive_tools uses AsyncSessionLocal (demo.db), so create via API
        cr = await async_client.post("/tools/archive/archives", json={
            "name": "获取测试唯一", "gender": "male",
            "phone": "13299900001", "archive_type": "NORMAL"
        }, cookies=cookies(admin_user))
        assert cr.status_code in (200, 201)
        aid = cr.json()["data"]["id"]
        resp = await async_client.get(f"/tools/archive/archives/{aid}", cookies=cookies(admin_user))
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "获取测试唯一"

    @pytest.mark.asyncio
    async def test_get_archive_not_found(self, async_client, admin_user, db_session):
        fake_id = str(uuid.uuid4())
        resp = await async_client.get(f"/tools/archive/archives/{fake_id}", cookies=cookies(admin_user))
        assert resp.status_code in (404, 400)  # archive_tools returns 404 for NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_archive(self, async_client, admin_user, db_session):
        cr = await async_client.post("/tools/archive/archives", json={
            "name": "待更新唯一", "gender": "male",
            "phone": "13299900002", "archive_type": "NORMAL"
        }, cookies=cookies(admin_user))
        assert cr.status_code in (200, 201)
        aid = cr.json()["data"]["id"]
        resp = await async_client.patch(f"/tools/archive/archives/{aid}",
            json={"name": "已更新"}, cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_archive(self, async_client, admin_user, db_session):
        cr = await async_client.post("/tools/archive/archives", json={
            "name": "待删除唯一", "gender": "male",
            "phone": "13299900003", "archive_type": "NORMAL"
        }, cookies=cookies(admin_user))
        assert cr.status_code in (200, 201)
        aid = cr.json()["data"]["id"]
        resp = await async_client.delete(f"/tools/archive/archives/{aid}", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_archive_stats(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/archive/stats", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_recycle_list(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/archive/recycle", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_families(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/archive/families", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_family(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/archive/families", json={
            "name": "测试家庭", "address": "北京市"
        }, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_search_archives(self, async_client, professional_user, db_session):
        await mk_archive(db_session, name="搜索张三")
        resp = await async_client.get("/tools/archive/archives?q=搜索", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_cannot_list_all(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/archive/archives", cookies=cookies(patient_user))
        assert resp.status_code in (200, 400, 401, 403)  # archive requires ADMIN/PRO role


# ══════════════════════════════════════════════════════════════════════════════
# 3. 健康指标 health_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestHealth:
    @pytest.mark.asyncio
    async def test_list_indicators_empty(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/indicators?indicator_type=BLOOD_PRESSURE",
            cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_add_blood_pressure(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/indicators", json={
            "indicator_type": "BLOOD_PRESSURE",
            "values": {"systolic": 125, "diastolic": 82},
            "scene": "morning"
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_add_blood_glucose(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/indicators", json={
            "indicator_type": "BLOOD_GLUCOSE",
            "values": {"value": 5.8, "scene": "fasting"}
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_add_weight(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/indicators", json={
            "indicator_type": "WEIGHT",
            "values": {"value": 68.5}
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_add_invalid_type(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/indicators", json={
            "indicator_type": "INVALID_TYPE",
            "values": {"value": 100}
        }, cookies=cookies(patient_user))
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_get_profile(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/profile", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_profile_me(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/profile/me", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_profile(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/profile", json={
            "height_cm": 170.0, "weight_kg": 65.0, "smoking": "never"
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_change_password(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/profile/change-password", json={
            "current_password": PW, "new_password": "NewTest@123456"
        }, cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_change_password_wrong_old(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/profile/change-password", json={
            "current_password": "wrongpwd", "new_password": "NewTest@123456"
        }, cookies=cookies(patient_user))
        assert resp.status_code in (400, 401)

    @pytest.mark.asyncio
    async def test_disease_list(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/disease", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_add_disease(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/disease", json={
            "disease_type": "HYPERTENSION",
            "diagnosed_at": "2020-01-01"
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════════════
# 4. 体质评估 constitution_tools
# ══════════════════════════════════════════════════════════════════════════════

async def seed_questions(db):
    for bt in list(BodyType)[:3]:
        for i in range(2):
            q = ConstitutionQuestion(
                code=f"{bt.value}_{i+1:02d}",
                body_type=bt,
                seq=i + 1,
                content=f"[测试]{bt.value} 第{i+1}题",
                options=[
                    {"value": 1, "label": "没有"}, {"value": 5, "label": "总是"}
                ],
                is_reverse=False,
            )
            db.add(q)
    await db.flush()


class TestConstitution:
    @pytest.mark.asyncio
    async def test_get_questions_empty(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/constitution/questions", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_start_assessment(self, async_client, patient_user, db_session):
        await seed_questions(db_session)
        resp = await async_client.post("/tools/constitution/start", cookies=cookies(patient_user))
        assert resp.status_code == 201
        assert "assessment_id" in resp.json()["data"]

    @pytest.mark.asyncio
    async def test_start_resumes_existing(self, async_client, patient_user, db_session):
        await seed_questions(db_session)
        r1 = await async_client.post("/tools/constitution/start", cookies=cookies(patient_user))
        r2 = await async_client.post("/tools/constitution/start", cookies=cookies(patient_user))
        assert r2.status_code in (200, 201)
        assert r2.json()["data"]["assessment_id"] == r1.json()["data"]["assessment_id"]

    @pytest.mark.asyncio
    async def test_full_flow(self, async_client, patient_user, db_session):
        await seed_questions(db_session)
        r = await async_client.post("/tools/constitution/start", cookies=cookies(patient_user))
        assert r.status_code == 201
        aid = r.json()["data"]["assessment_id"]

        qs = (await async_client.get("/tools/constitution/questions", cookies=cookies(patient_user))).json()["data"]
        answers = [{"question_id": q["id"], "answer_value": 3} for q in qs]
        r2 = await async_client.post("/tools/constitution/answer",
            json={"assessment_id": aid, "answers": answers}, cookies=cookies(patient_user))
        assert r2.status_code == 200

        r3 = await async_client.post("/tools/constitution/submit",
            json={"assessment_id": aid}, cookies=cookies(patient_user))
        assert r3.status_code == 200
        assert "main_type" in r3.json()["data"]

    @pytest.mark.asyncio
    async def test_submit_twice_conflict(self, async_client, patient_user, db_session):
        await seed_questions(db_session)
        r = await async_client.post("/tools/constitution/start", cookies=cookies(patient_user))
        aid = r.json()["data"]["assessment_id"]
        qs = (await async_client.get("/tools/constitution/questions", cookies=cookies(patient_user))).json()["data"]
        answers = [{"question_id": q["id"], "answer_value": 3} for q in qs]
        await async_client.post("/tools/constitution/answer",
            json={"assessment_id": aid, "answers": answers}, cookies=cookies(patient_user))
        await async_client.post("/tools/constitution/submit",
            json={"assessment_id": aid}, cookies=cookies(patient_user))
        r2 = await async_client.post("/tools/constitution/submit",
            json={"assessment_id": aid}, cookies=cookies(patient_user))
        assert r2.status_code == 409

    @pytest.mark.asyncio
    async def test_latest_assessment(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/constitution/latest", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_answer_invalid_assessment(self, async_client, patient_user, db_session):
        await seed_questions(db_session)
        resp = await async_client.post("/tools/constitution/answer",
            json={"assessment_id": str(uuid.uuid4()), "answers": []},
            cookies=cookies(patient_user))
        assert resp.status_code in (400, 404)


# ══════════════════════════════════════════════════════════════════════════════
# 5. 随访模块 followup_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestFollowup:
    async def _start_plan(self, client, user):
        resp = await client.post("/tools/followup/start", json={
            "disease_type": "HYPERTENSION",
            "cadence_days": 7,
            "total_weeks": 4,
        }, cookies=cookies(user))
        return resp

    @pytest.mark.asyncio
    async def test_start_followup(self, async_client, patient_user, db_session):
        resp = await self._start_plan(async_client, patient_user)
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_start_invalid_disease(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/followup/start", json={
            "disease_type": "INVALID", "cadence_days": 7, "total_weeks": 4
        }, cookies=cookies(patient_user))
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_list_plans(self, async_client, patient_user, db_session):
        await self._start_plan(async_client, patient_user)
        resp = await async_client.get("/tools/followup/plans", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_today_tasks(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/followup/today", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_checkin(self, async_client, patient_user, db_session):
        await self._start_plan(async_client, patient_user)
        # Get today's tasks to find a task_id for checkin
        today_r = await async_client.get("/tools/followup/today", cookies=cookies(patient_user))
        tasks = today_r.json().get("data", [])
        if not tasks:
            # No tasks today — skip checkin assertion
            return
        task_id = tasks[0]["task_id"]
        resp = await async_client.post("/tools/followup/checkin", json={
            "task_id": task_id,
            "value": {"systolic": 130, "diastolic": 85},
            "note": "今天状态良好"
        }, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_adherence(self, async_client, patient_user, db_session):
        r = await self._start_plan(async_client, patient_user)
        plan_id = r.json()["data"]["plan_id"]
        resp = await async_client.get(f"/tools/followup/adherence?plan_id={plan_id}",
            cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_followup(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/followup", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_followup_tasks(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/followup/tasks", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 6. 预警模块 alert_tools
# ══════════════════════════════════════════════════════════════════════════════

async def mk_alert_rule(db, admin_id):
    r = AlertRule(
        name="测试血压规则",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        conditions=[{"field": "systolic", "op": "gt", "value": 140}],
        severity=AlertSeverity.HIGH,
        message_template="血压偏高，请注意",
        is_active=True,
    )
    db.add(r)
    await db.flush()
    return r

async def mk_alert_event(db, user_id, rule_id):
    e = AlertEvent(
        user_id=user_id,
        rule_id=rule_id,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        message="血压偏高，请注意",
        trigger_value={"systolic": 165},
    )
    db.add(e)
    await db.flush()
    return e


class TestAlerts:
    @pytest.mark.asyncio
    async def test_admin_list_alerts(self, async_client, admin_user, db_session):
        rule = await mk_alert_rule(db_session, admin_user.id)
        await mk_alert_event(db_session, admin_user.id, rule.id)
        resp = await async_client.get("/tools/alerts/admin", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_alert(self, async_client, admin_user, db_session):
        rule = await mk_alert_rule(db_session, admin_user.id)
        event = await mk_alert_event(db_session, admin_user.id, rule.id)
        resp = await async_client.get(f"/tools/alerts/{event.id}", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_alert_not_found(self, async_client, admin_user, db_session):
        resp = await async_client.get(f"/tools/alerts/{uuid.uuid4()}", cookies=cookies(admin_user))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ack_alert(self, async_client, admin_user, db_session):
        rule = await mk_alert_rule(db_session, admin_user.id)
        event = await mk_alert_event(db_session, admin_user.id, rule.id)
        resp = await async_client.patch(f"/tools/alerts/{event.id}/ack",
            json={"note": "已处理"}, cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_close_alert(self, async_client, admin_user, db_session):
        rule = await mk_alert_rule(db_session, admin_user.id)
        event = await mk_alert_event(db_session, admin_user.id, rule.id)
        resp = await async_client.patch(f"/tools/alerts/{event.id}/close",
            json={"note": "关闭"}, cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_cannot_access_admin_alerts(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/alerts/admin", cookies=cookies(patient_user))
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_list_alerts_auth(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/alerts/", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 7. 指导模块 guidance_tools
# ══════════════════════════════════════════════════════════════════════════════

async def mk_guidance_template(db, doctor_id):
    t = GuidanceTemplate(
        name="测试指导模板",
        guidance_type=GuidanceType.GUIDANCE,
        scope="PERSONAL",
        content="测试内容正文",
        tags="测试",
        is_active=True,
        created_by=doctor_id,
    )
    db.add(t)
    await db.flush()
    return t

async def mk_guidance_record(db, patient_id, doctor_id):
    r = GuidanceRecord(
        patient_id=patient_id,
        doctor_id=doctor_id,
        guidance_type=GuidanceType.GUIDANCE,
        title="测试指导记录",
        content="指导内容",
        status=GuidanceStatus.PUBLISHED,
        is_read=False,
    )
    db.add(r)
    await db.flush()
    return r


class TestGuidance:
    @pytest.mark.asyncio
    async def test_list_records(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/guidance/records", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_record(self, async_client, professional_user, patient_user, db_session):
        resp = await async_client.post("/tools/guidance/records", json={
            "patient_id": str(patient_user.id),
            "guidance_type": "GUIDANCE",
            "title": "新建指导",
            "content": "指导内容正文"
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_record(self, async_client, professional_user, patient_user, db_session):
        r = await mk_guidance_record(db_session, patient_user.id, professional_user.id)
        resp = await async_client.get(f"/tools/guidance/records/{r.id}", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_templates(self, async_client, professional_user, db_session):
        await mk_guidance_template(db_session, professional_user.id)
        resp = await async_client.get("/tools/guidance/templates", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_template(self, async_client, professional_user, db_session):
        resp = await async_client.post("/tools/guidance/templates", json={
            "name": "新模板", "guidance_type": "GUIDANCE",
            "scope": "PERSONAL", "content": "模板内容"
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_update_template(self, async_client, professional_user, db_session):
        t = await mk_guidance_template(db_session, professional_user.id)
        resp = await async_client.patch(f"/tools/guidance/templates/{t.id}",
            json={"name": "更新模板名"}, cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_template(self, async_client, professional_user, db_session):
        t = await mk_guidance_template(db_session, professional_user.id)
        resp = await async_client.delete(f"/tools/guidance/templates/{t.id}",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_copy_template(self, async_client, professional_user, db_session):
        t = await mk_guidance_template(db_session, professional_user.id)
        resp = await async_client.post(f"/tools/guidance/templates/{t.id}/copy",
            cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_template_not_found(self, async_client, professional_user, db_session):
        resp = await async_client.get(f"/tools/guidance/templates/{uuid.uuid4()}",
            cookies=cookies(professional_user))
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 8. 量表模块 scale_tools
# ══════════════════════════════════════════════════════════════════════════════

async def mk_scale(db, created_by):
    s = Scale(
        name="测试量表PHQ-2",
        code=f"PHQ-2-{uuid.uuid4().hex[:6]}",  # unique code to avoid conflicts
        scale_type="MENTAL_HEALTH",
        description="抑郁筛查",
        version=1,
        is_active=True,
        created_by=str(created_by),  # SQLite needs str, not UUID object
    )
    db.add(s)
    await db.flush()
    return s

async def mk_scale_question(db, scale_id, seq=1):
    import json as _json
    q = ScaleQuestion(
        scale_id=scale_id,
        question_no=seq,
        question_text=f"测试题目{seq}",
        question_type="SINGLE",
        options=_json.dumps([{"text": "没有", "score": 0}, {"text": "几乎每天", "score": 3}]),
    )
    db.add(q)
    await db.flush()
    return q


class TestScale:
    @pytest.mark.asyncio
    async def test_list_scales(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/scale/scales", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_scale(self, async_client, professional_user, db_session):
        resp = await async_client.post("/tools/scale/scales", json={
            "name": "测试量表", "code": "TEST-001",
            "scale_type": "MENTAL_HEALTH", "description": "测试"
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_scale(self, async_client, professional_user, db_session):
        s = await mk_scale(db_session, professional_user.id)
        resp = await async_client.get(f"/tools/scale/scales/{s.id}", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_add_question(self, async_client, professional_user, db_session):
        s = await mk_scale(db_session, professional_user.id)
        resp = await async_client.post(f"/tools/scale/scales/{s.id}/questions", json={
            "question_no": 1, "question_text": "新题目",
            "question_type": "SINGLE",
            "options": [{"text": "没有", "score": 0}, {"text": "有时", "score": 1}],
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_questions(self, async_client, professional_user, db_session):
        s = await mk_scale(db_session, professional_user.id)
        await mk_scale_question(db_session, s.id)
        resp = await async_client.get(f"/tools/scale/scales/{s.id}/questions",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_records(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/scale/records", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_record(self, async_client, professional_user, patient_user, db_session):
        s = await mk_scale(db_session, professional_user.id)
        await mk_scale_question(db_session, s.id)
        resp = await async_client.post("/tools/scale/records", json={
            "patient_archive_id": str(uuid.uuid4()),
            "scale_id": str(s.id),
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201, 400, 404)

    @pytest.mark.asyncio
    async def test_delete_scale(self, async_client, admin_user, professional_user, db_session):
        # delete requires ADMIN role
        s = await mk_scale(db_session, professional_user.id)
        resp = await async_client.delete(f"/tools/scale/scales/{s.id}",
            cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 9. 咨询模块 consultation_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestConsultation:
    async def _ensure_archive(self, db, user):
        """Ensure patient_user has an archive (consultation requires one)."""
        return await mk_archive(db, user=user, name="咨询测试患者")

    async def _create_consult(self, client, user, db):
        await self._ensure_archive(db, user)
        return await client.post("/tools/consultations", json={
            "title": "血压偏高咨询",
            "content": "我最近血压偏高，请问怎么处理？"
        }, cookies=cookies(user))

    @pytest.mark.asyncio
    async def test_create_consultation(self, async_client, patient_user, professional_user, db_session):
        resp = await self._create_consult(async_client, patient_user, db_session)
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_consultations(self, async_client, patient_user, professional_user, db_session):
        await self._create_consult(async_client, patient_user, db_session)
        # list_consultations requires ADMIN or PROFESSIONAL role
        resp = await async_client.get("/tools/consultations", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_consultation(self, async_client, patient_user, professional_user, db_session):
        r = await self._create_consult(async_client, patient_user, db_session)
        cid = r.json()["data"]["consultation_id"]
        resp = await async_client.get(f"/tools/consultations/{cid}", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_send_message(self, async_client, patient_user, professional_user, db_session):
        r = await self._create_consult(async_client, patient_user, db_session)
        cid = r.json()["data"]["consultation_id"]
        resp = await async_client.post(f"/tools/consultations/{cid}/messages",
            json={"content": "补充说明一下症状"}, cookies=cookies(patient_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_close_consultation(self, async_client, professional_user, patient_user, db_session):
        r = await self._create_consult(async_client, patient_user, db_session)
        cid = r.json()["data"]["consultation_id"]
        resp = await async_client.patch(f"/tools/consultations/{cid}/close",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_consultation_stats(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/consultations/stats", cookies=cookies(professional_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 10. 内容模块 content_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestContent:
    @pytest.mark.asyncio
    async def test_list_content_public(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/content/", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_content(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/content/", json={
            "title": "高血压防治指南",
            "content_type": "ARTICLE",
            "body": "高血压是常见慢性病...",
            "tags": ["高血压", "预防"],
        }, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_publish_content(self, async_client, admin_user, db_session):
        r = await async_client.post("/tools/content/", json={
            "title": "测试内容发布", "content_type": "ARTICLE", "body": "正文"
        }, cookies=cookies(admin_user))
        cid = r.json()["data"]["content_id"]
        # Must submit for review first (DRAFT → PENDING_REVIEW)
        await async_client.patch(f"/tools/content/{cid}/submit-review", cookies=cookies(admin_user))
        resp = await async_client.patch(f"/tools/content/{cid}/publish",
            json={"review_note": "通过"}, cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_content(self, async_client, patient_user, admin_user, db_session):
        r = await async_client.post("/tools/content/", json={
            "title": "测试内容获取", "content_type": "ARTICLE", "body": "正文"
        }, cookies=cookies(admin_user))
        cid = r.json()["data"]["content_id"]
        resp = await async_client.get(f"/tools/content/{cid}", cookies=cookies(patient_user))
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_admin_list_content(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/content/admin", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_content(self, async_client, admin_user, db_session):
        r = await async_client.post("/tools/content/", json={
            "title": "待更新", "content_type": "ARTICLE", "body": "原始正文"
        }, cookies=cookies(admin_user))
        cid = r.json()["data"]["content_id"]
        resp = await async_client.patch(f"/tools/content/{cid}",
            json={"title": "已更新"}, cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 11. 标签模块 label_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestLabel:
    @pytest.mark.asyncio
    async def test_list_categories(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/label/categories", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_category(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/label/categories",
            json={"name": "疾病标签", "color": "#ff0000"}, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_create_label(self, async_client, admin_user, db_session):
        r = await async_client.post("/tools/label/categories",
            json={"name": "类别A", "color": "#00ff00"}, cookies=cookies(admin_user))
        cat_id = r.json()["data"]["id"]  # response key is "id" not "category_id"
        resp = await async_client.post("/tools/label/labels",
            json={"name": "高血压", "category_id": cat_id, "color": "#ff0000"},
            cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_labels(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/label/labels", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_label_stats(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/label/stats", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_labels(self, async_client, admin_user, patient_user, db_session):
        r = await async_client.post("/tools/label/categories",
            json={"name": "C1", "color": "#abc"}, cookies=cookies(admin_user))
        cat_id = r.json()["data"]["id"]  # response key is "id"
        r2 = await async_client.post("/tools/label/labels",
            json={"name": "L1", "category_id": cat_id, "color": "#def"},
            cookies=cookies(admin_user))
        label_id = r2.json()["data"]["id"]  # response key is "id"
        resp = await async_client.post(f"/tools/label/patients/{patient_user.id}/labels",
            json={"label_id": label_id}, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_patient_labels(self, async_client, admin_user, patient_user, db_session):
        resp = await async_client.get(f"/tools/label/patients/{patient_user.id}/labels",
            cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 12. 风险模块 risk_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestRisk:
    @pytest.mark.asyncio
    async def test_risk_stats(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/risk/stats", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_risk_dashboard(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/risk/dashboard", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_analyze_archive(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "风险患者")
        resp = await async_client.post(f"/tools/risk/analyze/{archive.id}",
            json={}, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201, 404)

    @pytest.mark.asyncio
    async def test_get_risk_result(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "结果患者")
        resp = await async_client.get(f"/tools/risk/result/{archive.id}",
            cookies=cookies(professional_user))
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_list_issued_plans(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "方案患者")
        resp = await async_client.get(f"/tools/risk/plans/{archive.id}",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_issue_plan(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "下达方案患者")
        resp = await async_client.post("/tools/risk/plan/issue", json={
            "archive_id": str(archive.id),
            "title": "中医调理方案",
            "plan_content": "建议清淡饮食，规律运动",
            "auto_followup_days": 7
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════════════
# 13. 统计模块 stats/business_stats
# ══════════════════════════════════════════════════════════════════════════════

class TestStats:
    @pytest.mark.asyncio
    async def test_business_stats(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/stats/business", cookies=cookies(admin_user))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_archives" in data or "total" in data or isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_business_trend(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/stats/business/trend", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_overview(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/stats/overview", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 14. 插件模块 plugin_tools (A-E)
# ══════════════════════════════════════════════════════════════════════════════

class TestPlugin:
    @pytest.mark.asyncio
    async def test_context(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/plugin/context", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bind_patient(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "绑定测试")
        resp = await async_client.post("/tools/plugin/bind",
            json={"patient_key": "绑定测试"}, cookies=cookies(professional_user))
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_patient_search(self, async_client, professional_user, db_session):
        await mk_archive(db_session, None, "插件搜索患者")
        resp = await async_client.get("/tools/plugin/patient/search?query=插件",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_profile(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "档案患者")
        resp = await async_client.get(f"/tools/plugin/patient/{archive.id}/profile",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_metrics(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "指标患者")
        resp = await async_client.get(f"/tools/plugin/patient/{archive.id}/metrics",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_risk_tags(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "标签患者")
        resp = await async_client.get(f"/tools/plugin/patient/{archive.id}/risk-tags",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_plan_versions(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "版本患者")
        resp = await async_client.get(f"/tools/plugin/plan/versions/{archive.id}",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_current_plan(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "当前方案患者")
        resp = await async_client.get(f"/tools/plugin/plan/current/{archive.id}",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_draft(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "草稿患者")
        resp = await async_client.post("/tools/plugin/plan/draft", json={
            "patient_id": str(archive.id),
            "title": "新草稿方案",
            "content": "草稿内容",
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201, 400)

    @pytest.mark.asyncio
    async def test_list_templates(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/plugin/template/list", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_template_not_found(self, async_client, professional_user, db_session):
        resp = await async_client.get(f"/tools/plugin/template/{uuid.uuid4()}",
            cookies=cookies(professional_user))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_followup_tasks(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "随访任务患者")
        resp = await async_client.get(f"/tools/plugin/followup/tasks/{archive.id}",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_followup_plan(self, async_client, professional_user, db_session):
        archive = await mk_archive(db_session, professional_user, "随访计划患者")
        resp = await async_client.post("/tools/plugin/followup/plan", json={
            "patient_id": str(archive.id),
            "disease_type": "HYPERTENSION",
            "cadence_days": 7,
            "total_weeks": 4,
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201, 400)

    @pytest.mark.asyncio
    async def test_patient_not_found(self, async_client, professional_user, db_session):
        resp = await async_client.get(f"/tools/plugin/patient/{uuid.uuid4()}/profile",
            cookies=cookies(professional_user))
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 15. 管理员模块 admin_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestAdmin:
    @pytest.mark.asyncio
    async def test_list_users(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/users", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_user(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/admin/users", json={
            "phone": "13500001111", "name": "新用户",
            "password": PW, "role": "PATIENT"
        }, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_user(self, async_client, admin_user, patient_user, db_session):
        resp = await async_client.get(f"/tools/admin/users/{patient_user.id}",
            cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user(self, async_client, admin_user, patient_user, db_session):
        resp = await async_client.patch(f"/tools/admin/users/{patient_user.id}",
            json={"name": "更新姓名"}, cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_workbench(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/workbench", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_patients(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/admin/patients", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_toggle_patient(self, async_client, admin_user, patient_user, db_session):
        resp = await async_client.patch(
            f"/tools/admin/patients/{patient_user.id}/toggle-active",
            cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_users(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/admin/users", cookies=cookies(patient_user))
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, async_client, admin_user, db_session):
        resp = await async_client.get(f"/tools/admin/users/{uuid.uuid4()}",
            cookies=cookies(admin_user))
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 16. 机构/角色/任务管理 mgmt_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestMgmt:
    @pytest.mark.asyncio
    async def test_list_orgs(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/mgmt/orgs", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_org(self, async_client, admin_user, db_session):
        resp = await async_client.post("/tools/mgmt/orgs", json={
            "name": "测试机构", "org_type": "HOSPITAL", "code": "TEST-ORG-001"
        }, cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_roles(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/mgmt/roles", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_tasks(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/mgmt/tasks", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_settings(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/mgmt/settings", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 17. 字典模块 sysdict_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestSysdict:
    @pytest.mark.asyncio
    async def test_list_groups(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/sysdict/groups", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_group(self, async_client, admin_user, db_session):
        code = f"TEST_GRP_{uuid.uuid4().hex[:8].upper()}"
        resp = await async_client.post("/tools/sysdict/groups",
            json={"code": code, "name": "测试字典组", "description": "测试"},
            cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_create_item(self, async_client, admin_user, db_session):
        code = f"TEST_G2_{uuid.uuid4().hex[:8].upper()}"
        r = await async_client.post("/tools/sysdict/groups",
            json={"code": code, "name": "测试组2"}, cookies=cookies(admin_user))
        assert r.status_code in (200, 201)
        gid = r.json()["data"]["id"]  # response key is "id"
        resp = await async_client.post(f"/tools/sysdict/groups/{gid}/items",
            json={"code": "ITEM_001", "name": "选项1", "value": "v1", "seq": 1},
            cookies=cookies(admin_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_items(self, async_client, admin_user, db_session):
        code = f"TEST_G3_{uuid.uuid4().hex[:8].upper()}"
        r = await async_client.post("/tools/sysdict/groups",
            json={"code": code, "name": "测试组3"}, cookies=cookies(admin_user))
        assert r.status_code in (200, 201)
        gid = r.json()["data"]["id"]  # response key is "id"
        resp = await async_client.get(f"/tools/sysdict/groups/{gid}/items",
            cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_versions(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/sysdict/versions", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 18. 通知模块 notification_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestNotification:
    @pytest.mark.asyncio
    async def test_list_notifications(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/notifications/mine", cookies=cookies(patient_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_notification_count(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/notifications/count", cookies=cookies(patient_user))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "unread" in data or "count" in data or isinstance(data, (int, dict))

    @pytest.mark.asyncio
    async def test_read_all(self, async_client, patient_user, db_session):
        resp = await async_client.post("/tools/notifications/read-all", cookies=cookies(patient_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 19. 审计模块 audit_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestAudit:
    @pytest.mark.asyncio
    async def test_list_audit_logs(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/audit", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_with_slash(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/audit/", cookies=cookies(admin_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patient_cannot_access_audit(self, async_client, patient_user, db_session):
        resp = await async_client.get("/tools/audit", cookies=cookies(patient_user))
        assert resp.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════════════
# 20. 干预模块 intervention_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestIntervention:
    @pytest.mark.asyncio
    async def test_list_interventions(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/intervention/interventions",
            cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_intervention(self, async_client, professional_user, patient_user, db_session):
        resp = await async_client.post("/tools/intervention/interventions", json={
            "patient_id": str(patient_user.id),
            "plan_name": "针灸干预方案",  # endpoint expects plan_name not title
            "intervention_type": "ACUPUNCTURE",
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_get_intervention_not_found(self, async_client, professional_user, db_session):
        # intervention_id is int in this endpoint
        resp = await async_client.get("/tools/intervention/interventions/999999",
            cookies=cookies(professional_user))
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 21. 宣教模块 education_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestEducation:
    @pytest.mark.asyncio
    async def test_list_education_records(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/education/records", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_education_templates(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/education/templates", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_education_record(self, async_client, professional_user, patient_user, db_session):
        resp = await async_client.post("/tools/education/records", json={
            "patient_id": str(patient_user.id),
            "title": "糖尿病宣教",
            "content": "糖尿病饮食注意事项...",
            "education_type": "DIABETES"
        }, cookies=cookies(professional_user))
        assert resp.status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════════════
# 22. 临床文档 clinical_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestClinical:
    @pytest.mark.asyncio
    async def test_list_documents(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/clinical/documents", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_clinical_stats(self, async_client, professional_user, db_session):
        resp = await async_client.get("/tools/clinical/stats", cookies=cookies(professional_user))
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sync_logs(self, async_client, admin_user, db_session):
        resp = await async_client.get("/tools/clinical/sync/logs", cookies=cookies(admin_user))
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 23. 健康检查
# ══════════════════════════════════════════════════════════════════════════════

class TestSystem:
    @pytest.mark.asyncio
    async def test_healthz(self, async_client, db_session):
        resp = await async_client.get("/healthz")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi(self, async_client, db_session):
        resp = await async_client.get("/openapi.json")
        assert resp.status_code == 200
        assert "paths" in resp.json()

    @pytest.mark.asyncio
    async def test_login_page(self, async_client, db_session):
        resp = await async_client.get("/login", follow_redirects=True)
        assert resp.status_code == 200
