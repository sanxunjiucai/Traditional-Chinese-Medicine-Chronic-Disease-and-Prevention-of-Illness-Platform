"""
专为 patient@tcm 账号补充 H5 端可见数据
user_id  = df6ffc0f488b4fd9bbdca426215ba4cd
archive_id = af84327b4bb748b0993c2eeab4b9e6c7
"""
import asyncio, uuid, json, random, sys
from datetime import datetime, timedelta, timezone, date

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__file__)))

from sqlalchemy import text
from app.database import AsyncSessionLocal

UTC = timezone.utc
PATIENT_UID = "df6ffc0f488b4fd9bbdca426215ba4cd"
ARCHIVE_ID  = "af84327b4bb748b0993c2eeab4b9e6c7"

def now(offset_days=0):
    return (datetime.now(UTC) - timedelta(days=offset_days)).strftime("%Y-%m-%d %H:%M:%S")

def rand_dt(start=60, end=1):
    return now(random.randint(end, start))

def uid():
    return str(uuid.uuid4())


async def main():
    async with AsyncSessionLocal() as db:

        # ── 1. health_profile ──────────────────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM health_profiles WHERE user_id=:u"), {"u": PATIENT_UID})
        if r.scalar() == 0:
            await db.execute(text("""
                INSERT INTO health_profiles
                    (id, user_id, gender, birth_date, height_cm, weight_kg, waist_cm,
                     past_history, family_history, allergy_history,
                     smoking, drinking, exercise_frequency, sleep_hours, stress_level)
                VALUES (:id,:u,'FEMALE','1975-08-12',162,62.5,78.0,
                    '高血压病史5年','父亲有糖尿病','青霉素过敏',
                    'NEVER','OCCASIONALLY','SOMETIMES',7,'MEDIUM')
            """), {"id": uid(), "u": PATIENT_UID})
            print("  health_profiles: 1 条插入")
        else:
            print("  health_profiles: 已存在，跳过")

        # ── 2. health_indicators ──────────────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM health_indicators WHERE user_id=:u"), {"u": PATIENT_UID})
        if r.scalar() < 10:
            def bp():
                return json.dumps({"systolic": random.randint(125, 155), "diastolic": random.randint(78, 95)})
            def bg():
                return json.dumps({"value": round(random.uniform(5.5, 8.5), 1), "timing": random.choice(["FASTING", "POSTMEAL"])})
            def hr():
                return json.dumps({"value": random.randint(68, 88)})
            def wt():
                return json.dumps({"value": round(random.uniform(61.0, 64.0), 1)})

            types = [
                ("BLOOD_PRESSURE", bp), ("BLOOD_PRESSURE", bp), ("BLOOD_PRESSURE", bp),
                ("BLOOD_GLUCOSE",  bg), ("BLOOD_GLUCOSE",  bg),
                ("HEART_RATE",     hr),
                ("WEIGHT",         wt),
            ]
            for i in range(30):
                itype, val_fn = random.choice(types)
                await db.execute(text("""
                    INSERT INTO health_indicators (id, user_id, indicator_type, "values", scene, recorded_at)
                    VALUES (:id,:u,:t,:v,'HOME',:at)
                """), {"id": uid(), "u": PATIENT_UID, "t": itype, "v": val_fn(),
                       "at": rand_dt(30, 0)})
            print("  health_indicators: 30 条插入")
        else:
            print("  health_indicators: 已存在，跳过")

        # ── 3. constitution_assessments ───────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM constitution_assessments WHERE user_id=:u"), {"u": PATIENT_UID})
        if r.scalar() == 0:
            for status, main_type, result_obj, days_ago in [
                ("REPORTED", "QI_DEFICIENCY",
                 {"main": "QI_DEFICIENCY", "score": 72, "label": "气虚质",
                  "suggestion": "宜补气健脾，注意休息，避免过度劳累，饮食以温软为主"}, 45),
                ("REPORTED", "YIN_DEFICIENCY",
                 {"main": "YIN_DEFICIENCY", "score": 68, "label": "阴虚质",
                  "suggestion": "宜滋阴润燥，避免熬夜，少食辛辣刺激食物"}, 5),
            ]:
                await db.execute(text("""
                    INSERT INTO constitution_assessments
                        (id, user_id, status, main_type, result, secondary_types, submitted_at, scored_at)
                    VALUES (:id,:u,:s,:m,:r,'[]',:sub,:sc)
                """), {"id": uid(), "u": PATIENT_UID, "s": status, "m": main_type,
                       "r": json.dumps(result_obj, ensure_ascii=False),
                       "sub": now(days_ago), "sc": now(days_ago)})
            print("  constitution_assessments: 2 条插入")
        else:
            print("  constitution_assessments: 已存在，跳过")

        # ── 4. followup_plans + tasks + checkins ─────────────
        r = await db.execute(text("SELECT COUNT(*) FROM followup_plans WHERE user_id=:u"), {"u": PATIENT_UID})
        if r.scalar() == 0:
            plan_id = uid()
            start = (date.today() - timedelta(days=20)).isoformat()
            end   = (date.today() + timedelta(days=40)).isoformat()
            await db.execute(text("""
                INSERT INTO followup_plans (id, user_id, disease_type, status, start_date, end_date, note)
                VALUES (:id,:u,'HYPERTENSION','IN_PROGRESS',:s,:e,'高血压30天随访计划')
            """), {"id": plan_id, "u": PATIENT_UID, "s": start, "e": end})

            tasks_def = [
                ("血压记录",   "INDICATOR_REPORT", -18),
                ("用药记录",   "MEDICATION",       -14),
                ("血压记录",   "INDICATOR_REPORT",  -7),
                ("饮食打卡",   "DIET",              -3),
                ("今日血压",   "INDICATOR_REPORT",   0),
                ("运动打卡",   "EXERCISE",           3),
                ("复诊提醒",   "VISIT",             10),
            ]
            for name, ttype, d_offset in tasks_def:
                task_id = uid()
                sched = (date.today() + timedelta(days=d_offset)).isoformat()
                await db.execute(text("""
                    INSERT INTO followup_tasks (id, plan_id, task_type, name, scheduled_date, required)
                    VALUES (:id,:pid,:t,:n,:s,1)
                """), {"id": task_id, "pid": plan_id, "t": ttype, "n": name, "s": sched})
                if d_offset < 0:
                    done = random.random() > 0.3
                    await db.execute(text("""
                        INSERT INTO checkins (id, task_id, user_id, status, checked_at)
                        VALUES (:id,:tid,:u,:s,:at)
                    """), {"id": uid(), "tid": task_id, "u": PATIENT_UID,
                           "s": "DONE" if done else "MISSED",
                           "at": now(abs(d_offset)) if done else None})
            print("  followup_plans + tasks + checkins: 插入完成")
        else:
            print("  followup_plans: 已存在，跳过")

        # ── 5. recommendation_plans ───────────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM recommendation_plans WHERE user_id=:u"), {"u": PATIENT_UID})
        if r.scalar() == 0:
            items = json.dumps([
                {"type": "DIET",     "title": "低盐低脂饮食方案", "content": "每日食盐<6g，减少动物脂肪，多食蔬菜水果"},
                {"type": "EXERCISE", "title": "有氧运动计划",     "content": "每日步行30分钟，每周太极拳3次"},
                {"type": "HERB",     "title": "中药调理方案",     "content": "黄芪15g、党参10g、白术10g、茯苓10g，水煎服"},
                {"type": "ACUPOINT", "title": "穴位保健",         "content": "每日按摩足三里、气海穴各5分钟"},
            ], ensure_ascii=False)
            await db.execute(text("""
                INSERT INTO recommendation_plans (id, user_id, status, version, items, note)
                VALUES (:id,:u,'ACTIVE',1,:items,'气虚质综合调护方案')
            """), {"id": uid(), "u": PATIENT_UID, "items": items})
            print("  recommendation_plans: 1 条插入")
        else:
            print("  recommendation_plans: 已存在，跳过")

        # ── 6. notifications (archive_id) ────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM notifications WHERE archive_id=:a"), {"a": ARCHIVE_ID})
        if r.scalar() < 5:
            notifs = [
                ("ALERT",      "血压预警通知",    "您昨日血压145/92mmHg，偏高，建议复查并联系您的健康管理师。",   False),
                ("FOLLOWUP",   "随访任务提醒",    "您有今日血压测量任务待完成，请及时记录。",                       False),
                ("PLAN_ISSUED","健康方案已更新",   "您的气虚质调护方案已更新，点击查看新方案。",                     True),
                ("SYSTEM",     "平台维护通知",    "系统将于2026-03-10 02:00—04:00维护，请提前知悉。",              True),
                ("EDUCATION",  "健康知识推送",    "《气虚体质的饮食调养》已发布，点击阅读。",                       True),
            ]
            for ntype, title, content, read in notifs:
                await db.execute(text("""
                    INSERT INTO notifications
                        (id, archive_id, notif_type, title, content, status, read_at, created_at)
                    VALUES (:id,:a,:t,:ti,:c,:s,:rat,:cat)
                """), {"id": uid(), "a": ARCHIVE_ID,
                       "t": ntype, "ti": title, "c": content,
                       "s": "READ" if read else "UNREAD",
                       "rat": rand_dt(5, 1) if read else None,
                       "cat": rand_dt(10, 0)})
            print("  notifications: 5 条插入")
        else:
            print("  notifications: 已存在，跳过")

        # ── 7. consultations (archive_id) ────────────────────
        r = await db.execute(text("SELECT COUNT(*) FROM consultations WHERE archive_id=:a"), {"a": ARCHIVE_ID})
        if r.scalar() < 3:
            dr = await db.execute(text("SELECT id FROM users WHERE role='PROFESSIONAL' LIMIT 1"))
            doctor_id = dr.scalar()
            consults = [
                ("血压控制咨询",
                 "最近血压控制不稳定，早上经常140+，需要调整用药吗？",
                 "您好，根据您的血压记录，建议继续当前用药方案，同时注意低盐饮食和情绪管理。下次随访时我们详细讨论。",
                 "REPLIED"),
                ("中药调理体质",
                 "体质评估结果是气虚质，有推荐的中药调理方案吗？",
                 "气虚质患者推荐黄芪、党参等补气药材，可以煮粥或代茶饮。我已为您更新了调护方案，请查看。",
                 "REPLIED"),
                ("头晕头痛问题",
                 "最近早上起床时有些头晕，血压145/90，正常吗？",
                 None,
                 "OPEN"),
            ]
            for title, q, reply, status in consults:
                cid = uid()
                created = rand_dt(30, 3)
                await db.execute(text("""
                    INSERT INTO consultations
                        (id, archive_id, doctor_id, title, status, priority, created_at, updated_at)
                    VALUES (:id,:a,:did,:t,:s,'NORMAL',:cat,:cat)
                """), {"id": cid, "a": ARCHIVE_ID, "did": doctor_id,
                       "t": title, "s": status, "cat": created})
                # 患者消息
                await db.execute(text("""
                    INSERT INTO consultation_messages
                        (id, consultation_id, sender_id, sender_type, content, msg_type, created_at)
                    VALUES (:id,:cid,:sid,'PATIENT',:c,'TEXT',:at)
                """), {"id": uid(), "cid": cid, "sid": ARCHIVE_ID, "c": q, "at": created})
                if reply:
                    reply_t = (datetime.now(UTC) - timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d %H:%M:%S")
                    await db.execute(text("""
                        INSERT INTO consultation_messages
                            (id, consultation_id, sender_id, sender_type, content, msg_type, created_at)
                        VALUES (:id,:cid,:sid,'DOCTOR',:c,'TEXT',:at)
                    """), {"id": uid(), "cid": cid, "sid": doctor_id, "c": reply, "at": reply_t})
            print("  consultations: 3 条插入")
        else:
            print("  consultations: 已存在，跳过")

        await db.commit()

    print("\n=== patient@tcm H5数据补充完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
