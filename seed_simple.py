"""简化数据填充"""
import sqlite3
import json
import uuid
from datetime import datetime, timedelta

conn = sqlite3.connect('demo.db')
c = conn.cursor()

# 获取患者
c.execute('SELECT id, name FROM patient_archives WHERE is_deleted = 0 LIMIT 15')
patients = c.fetchall()
print(f"✓ 找到 {len(patients)} 个患者")

# 1. 宣教发送记录
c.execute('PRAGMA table_info(education_deliveries)')
cols = [row[1] for row in c.fetchall()]
print(f"education_deliveries 字段: {cols}")

c.execute('DELETE FROM education_deliveries')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO education_deliveries
        (record_id, patient_id, delivered_at, send_method, read_status)
        VALUES (?, ?, ?, ?, ?)''',
        (1+i, pid,
         (datetime.now() - timedelta(days=10+i*2)).isoformat(),
         ['FACE_TO_FACE', 'PHONE', 'SMS'][i % 3],
         ['READ', 'UNREAD'][i % 2]))

conn.commit()
print(f"✓ 已添加 10 条宣教发送记录")

# 2. 指导记录
c.execute('PRAGMA table_info(guidance_records)')
cols = [row[1] for row in c.fetchall()]
print(f"guidance_records 字段: {cols}")

c.execute('DELETE FROM guidance_records')
for i, (pid, name) in enumerate(patients[:8]):
    c.execute('''INSERT INTO guidance_records
        (id, archive_id, template_id, guidance_date, content, follow_up_required,
         follow_up_date, status, created_by, created_at, updated_at, notes, attachments)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid, None,
         (datetime.now() - timedelta(days=15+i*2)).isoformat(),
         '详细的中医指导内容...',
         1 if i % 2 == 0 else 0,
         (datetime.now() + timedelta(days=30)).isoformat() if i % 2 == 0 else None,
         ['COMPLETED', 'IN_PROGRESS'][i % 2],
         None,
         datetime.now().isoformat(),
         datetime.now().isoformat(),
         '患者配合良好',
         None))

conn.commit()
print(f"✓ 已添加 8 条指导记录")

# 3. 咨询记录
c.execute('DELETE FROM consultations')
c.execute('DELETE FROM consultation_messages')
for i, (pid, name) in enumerate(patients[:5]):
    cid = str(uuid.uuid4())
    c.execute('''INSERT INTO consultations
        (id, archive_id, title, category, status, priority, created_at, updated_at, closed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (cid, pid,
         ['血压控制咨询', '用药疑问', '饮食建议'][i % 3],
         ['CHRONIC_DISEASE', 'MEDICATION', 'NUTRITION'][i % 3],
         ['CLOSED', 'IN_PROGRESS'][i % 2],
         ['NORMAL', 'HIGH'][i % 2],
         (datetime.now() - timedelta(days=5+i)).isoformat(),
         datetime.now().isoformat(),
         datetime.now().isoformat() if i % 2 == 0 else None))

    # 添加消息
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
print(f"✓ 已添加 5 条咨询记录")

# 4. 通知
c.execute('DELETE FROM notifications')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO notifications
        (id, user_id, title, content, type, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['随访提醒', '体检通知', '用药提醒'][i % 3],
         '详细通知内容...',
         ['FOLLOWUP', 'EXAMINATION', 'MEDICATION'][i % 3],
         i % 3 == 0,
         (datetime.now() - timedelta(days=i)).isoformat()))

conn.commit()
print(f"✓ 已添加 10 条通知")

# 5. 健康指标
c.execute('DELETE FROM health_indicators')
for i, (pid, name) in enumerate(patients[:8]):
    for j in range(3):
        c.execute('''INSERT INTO health_indicators
            (id, archive_id, indicator_type, value, unit, measured_at, is_abnormal, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), pid,
             ['BLOOD_PRESSURE', 'BLOOD_SUGAR', 'WEIGHT'][j],
             [f"{120+i*3}/{75+i*2}", f"{5.5+i*0.2:.1f}", f"{65+i*2}"][j],
             ['mmHg', 'mmol/L', 'kg'][j],
             (datetime.now() - timedelta(days=j*7)).isoformat(),
             i % 3 == 0,
             datetime.now().isoformat()))

conn.commit()
print(f"✓ 已添加 24 条健康指标")

conn.close()
print("\n✅ 数据填充完成！")
