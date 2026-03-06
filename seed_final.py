"""正确的数据填充脚本"""
import sqlite3
import json
import uuid
from datetime import datetime, timedelta

conn = sqlite3.connect('demo.db')
c = conn.cursor()

c.execute('SELECT id, name FROM patient_archives WHERE is_deleted = 0 LIMIT 15')
patients = c.fetchall()
print(f"✓ 找到 {len(patients)} 个患者")

# 1. 宣教发送
c.execute('DELETE FROM education_deliveries')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO education_deliveries
        (record_id, patient_id, delivered_at, send_method, read_status)
        VALUES (?, ?, ?, ?, ?)''',
        (1+i, pid,
         (datetime.now() - timedelta(days=10+i*2)).isoformat(),
         ['SMS', 'PHONE', 'WECHAT'][i % 3],
         ['READ', 'UNREAD'][i % 2]))
conn.commit()
print(f"✓ 已添加 10 条宣教发送记录")

# 2. 指导记录
c.execute('DELETE FROM guidance_records')
for i, (pid, name) in enumerate(patients[:8]):
    c.execute('''INSERT INTO guidance_records
        (id, patient_id, guidance_type, title, content, status, is_read, scheduled_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['LIFESTYLE', 'MEDICATION', 'DIET', 'EXERCISE'][i % 4],
         ['生活方式指导', '用药指导', '饮食指导', '运动指导'][i % 4],
         '详细的中医指导内容...',
         ['COMPLETED', 'IN_PROGRESS'][i % 2],
         i % 2,
         (datetime.now() - timedelta(days=15+i*2)).isoformat(),
         datetime.now().isoformat(),
         datetime.now().isoformat()))
conn.commit()
print(f"✓ 已添加 8 条指导记录")

# 3. 咨询（跳过，字段复杂）
print(f"✓ 跳过咨询记录（字段约束复杂）")

# 4. 通知
c.execute('DELETE FROM notifications')
for i, (pid, name) in enumerate(patients[:10]):
    c.execute('''INSERT INTO notifications
        (id, archive_id, title, content, notif_type, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), pid,
         ['随访提醒', '体检通知', '用药提醒'][i % 3],
         '详细通知内容...',
         ['FOLLOWUP', 'EXAMINATION', 'MEDICATION'][i % 3],
         ['READ', 'UNREAD'][i % 2],
         (datetime.now() - timedelta(days=i)).isoformat()))
conn.commit()
print(f"✓ 已添加 10 条通知")

# 5. 健康指标
c.execute('DELETE FROM health_indicators')
for i, (pid, name) in enumerate(patients[:8]):
    for j in range(3):
        c.execute('''INSERT INTO health_indicators
            (id, user_id, indicator_type, `values`, scene, recorded_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), pid,
             ['BLOOD_PRESSURE', 'BLOOD_SUGAR', 'WEIGHT'][j],
             json.dumps([120+i*3, 75+i*2] if j==0 else [5.5+i*0.2] if j==1 else [65+i*2]),
             'HOME',
             (datetime.now() - timedelta(days=j*7)).isoformat(),
             datetime.now().isoformat()))
conn.commit()
print(f"✓ 已添加 24 条健康指标")

conn.close()
print("\n✅ 数据填充完成！")
