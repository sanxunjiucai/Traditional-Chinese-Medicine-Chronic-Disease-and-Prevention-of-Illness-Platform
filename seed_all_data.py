"""完整演示数据填充 - 使用SQL直接插入"""
import sqlite3
import json
import uuid
from datetime import datetime, timedelta

conn = sqlite3.connect('demo.db')
c = conn.cursor()

# 获取现有患者
c.execute('SELECT id, name FROM patient_archives WHERE is_deleted = 0 LIMIT 15')
patients = c.fetchall()

if len(patients) < 5:
    print("患者数据不足")
    conn.close()
    exit(1)

print(f"✓ 找到 {len(patients)} 个患者")

# 1. 补充宣教记录
c.execute('DELETE FROM education_records')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO education_records
        (id, patient_id, title, content, category, delivery_method, duration_minutes,
         education_date, feedback, effectiveness, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['高血压健康教育', '糖尿病饮食指导', '中医养生知识', '运动康复指导', '用药指导'][i % 5],
         '详细的健康教育内容，包括疾病知识、日常护理、饮食建议等。',
         ['CHRONIC_DISEASE', 'TCM_HEALTH', 'NUTRITION', 'EXERCISE', 'MEDICATION'][i % 5],
         ['FACE_TO_FACE', 'PHONE', 'VIDEO', 'GROUP'][i % 4],
         30 + i * 5,
         (datetime.now() - timedelta(days=10+i*3)).isoformat(),
         '患者理解良好，能够配合执行',
         ['EXCELLENT', 'GOOD', 'FAIR'][i % 3],
         datetime.now().isoformat(),
         datetime.now().isoformat()))

conn.commit()
print(f"✓ 已添加 10 条宣教记录")

# 2. 补充量表记录
c.execute('SELECT id, name FROM scales LIMIT 4')
scales = c.fetchall()

if scales:
    c.execute('DELETE FROM scale_records')
    for i, (pid, pname) in enumerate(patients[:8]):
        scale = scales[i % len(scales)]
        c.execute('''INSERT INTO scale_records
            (id, patient_id, scale_id, assessment_date, answers, total_score,
             completed_at, conclusion, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), pid, scale[0],
             (datetime.now() - timedelta(days=20+i*5)).isoformat(),
             json.dumps({"q1": "2", "q2": "1", "q3": "3"}),
             12 + i * 2,
             (datetime.now() - timedelta(days=20+i*5)).isoformat(),
             ['评估结果正常', '轻度异常，建议关注', '需要进一步检查'][i % 3],
             datetime.now().isoformat(),
             datetime.now().isoformat()))

    conn.commit()
    print(f"✓ 已添加 8 条量表记录")

# 3. 补充随访任务
c.execute('SELECT id FROM followup_plans LIMIT 8')
plans = c.fetchall()

if plans:
    c.execute('DELETE FROM followup_tasks')
    for i, (plan_id,) in enumerate(plans):
        for j in range(2):
            c.execute('''INSERT INTO followup_tasks
                (id, plan_id, scheduled_date, status, actual_date, blood_pressure,
                 blood_sugar, symptoms, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (str(uuid.uuid4()), plan_id,
                 (datetime.now() - timedelta(days=15*j+i*3)).isoformat(),
                 ['COMPLETED', 'PENDING'][j % 2],
                 (datetime.now() - timedelta(days=15*j+i*3)).isoformat() if j == 0 else None,
                 f"{120+i*5}/{75+i*3}" if j == 0 else None,
                 f"{5.5+i*0.3:.1f}" if j == 0 else None,
                 ['无明显不适', '偶有头晕', '睡眠欠佳'][i % 3] if j == 0 else None,
                 '患者状态良好，继续观察' if j == 0 else None,
                 datetime.now().isoformat(),
                 datetime.now().isoformat()))

    conn.commit()
    print(f"✓ 已添加 {len(plans)*2} 条随访任务")

# 4. 补充干预记录
c.execute('DELETE FROM intervention_records')
for i, (pid, name) in enumerate(patients[:8]):
    c.execute('''INSERT INTO intervention_records
        (id, patient_id, intervention_type, title, content, start_date, end_date,
         frequency, status, progress_notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['MEDICATION', 'EXERCISE', 'DIET', 'TCM'][i % 4],
         ['降压药物治疗', '有氧运动计划', '低盐饮食方案', '中药调理'][i % 4],
         '详细的干预方案内容...',
         (datetime.now() - timedelta(days=30)).isoformat(),
         (datetime.now() + timedelta(days=60)).isoformat(),
         ['DAILY', 'WEEKLY', 'BIWEEKLY'][i % 3],
         ['IN_PROGRESS', 'COMPLETED'][i % 2],
         '患者依从性良好',
         datetime.now().isoformat(),
         datetime.now().isoformat()))

conn.commit()
print(f"✓ 已添加 8 条干预记录")

# 5. 补充指导记录
c.execute('DELETE FROM guidance_records')
for i, (pid, name) in enumerate(patients[:6]):
    c.execute('''INSERT INTO guidance_records
        (id, patient_id, guidance_type, title, content, guidance_date,
         follow_up_required, follow_up_date, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['LIFESTYLE', 'MEDICATION', 'DIET', 'EXERCISE'][i % 4],
         ['生活方式指导', '用药指导', '饮食指导', '运动指导'][i % 4],
         '详细的指导内容...',
         (datetime.now() - timedelta(days=15+i*2)).isoformat(),
         1 if i % 2 == 0 else 0,
         (datetime.now() + timedelta(days=30)).isoformat() if i % 2 == 0 else None,
         ['COMPLETED', 'IN_PROGRESS'][i % 2],
         datetime.now().isoformat(),
         datetime.now().isoformat()))

conn.commit()
print(f"✓ 已添加 6 条指导记录")

# 6. 补充咨询记录
c.execute('DELETE FROM consultations')
for i, (pid, name) in enumerate(patients[:5]):
    cid = str(uuid.uuid4())
    c.execute('''INSERT INTO consultations
        (id, patient_id, title, category, status, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (cid, pid,
         ['血压控制咨询', '用药疑问', '饮食建议', '体检报告解读'][i % 4],
         ['CHRONIC_DISEASE', 'MEDICATION', 'NUTRITION', 'EXAMINATION'][i % 4],
         ['CLOSED', 'IN_PROGRESS'][i % 2],
         ['NORMAL', 'HIGH'][i % 2],
         (datetime.now() - timedelta(days=5+i)).isoformat(),
         datetime.now().isoformat()))

    # 添加咨询消息
    c.execute('''INSERT INTO consultation_messages
        (id, consultation_id, sender_type, content, created_at)
        VALUES (?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), cid, 'PATIENT',
         '医生您好，我想咨询一下...',
         (datetime.now() - timedelta(days=5+i)).isoformat()))

    c.execute('''INSERT INTO consultation_messages
        (id, consultation_id, sender_type, content, created_at)
        VALUES (?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), cid, 'DOCTOR',
         '您好，根据您的情况，建议...',
         (datetime.now() - timedelta(days=5+i, hours=2)).isoformat()))

conn.commit()
print(f"✓ 已添加 5 条咨询记录及消息")

# 7. 补充通知记录
c.execute('DELETE FROM notifications')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO notifications
        (id, user_id, title, content, type, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['随访提醒', '体检通知', '用药提醒', '健康资讯'][i % 4],
         '详细通知内容...',
         ['FOLLOWUP', 'EXAMINATION', 'MEDICATION', 'INFO'][i % 4],
         i % 3 == 0,
         (datetime.now() - timedelta(days=i)).isoformat()))

conn.commit()
print(f"✓ 已添加 10 条通知记录")

# 8. 补充健康指标
c.execute('DELETE FROM health_indicators')
for i, (pid, name) in enumerate(patients[:8]):
    for j in range(5):
        c.execute('''INSERT INTO health_indicators
            (id, patient_id, indicator_type, value, unit, measured_at,
             is_abnormal, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), pid,
             ['BLOOD_PRESSURE', 'BLOOD_SUGAR', 'WEIGHT', 'HEART_RATE'][j % 4],
             [f"{120+i*3}/{75+i*2}", f"{5.5+i*0.2:.1f}", f"{65+i*2}", f"{72+i}"][j % 4],
             ['mmHg', 'mmol/L', 'kg', 'bpm'][j % 4],
             (datetime.now() - timedelta(days=j*7)).isoformat(),
             i % 3 == 0,
             datetime.now().isoformat()))

conn.commit()
print(f"✓ 已添加 40 条健康指标记录")

conn.close()
print("\n✅ 所有数据填充完成！")
