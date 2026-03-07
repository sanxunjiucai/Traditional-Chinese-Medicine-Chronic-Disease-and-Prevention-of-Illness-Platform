"""
赵建民 全量演示数据种子脚本
覆盖插件端 Step 0-15 所有功能节点：
  基本档案 / 健康档案 / 慢病记录 / 体质评估 /
  健康指标(90天) / 预警事件(OPEN) / 随访计划+任务+打卡 /
  指导方案(草稿+当前) / 干预记录
"""
import json, sqlite3, uuid
from datetime import date, datetime, timedelta

DB = "demo.db"
DOCTOR_ID = "0bcbd56da9f042b0b48007087d02a618"  # doctor@tcm

# ── 固定 UUID（幂等重跑不重复）───────────────────────────────────────────────
U   = lambda s: uuid.uuid5(uuid.NAMESPACE_URL, f"zbm/{s}").hex          # hex 无连字符
UID  = U("user")          # 系统用户
AID  = U("archive")       # 档案
HPID = U("health_profile")
CD1  = U("chronic_hyp")   # 高血压
CD2  = U("chronic_dm2")   # 2型糖尿病
CAI  = U("constitution")  # 体质评估
# health indicators
def IID(n): return U(f"indicator_{n}")
# alert events
AL1  = U("alert_high_bp")
AL2  = U("alert_med_bg")
AL3  = U("alert_med_bp")
# followup
FP1  = U("followup_plan1")
def TID(n): return U(f"task_{n}")
def CID(n): return U(f"checkin_{n}")
# guidance
GR1  = U("guidance_draft")
GR2  = U("guidance_published")
# intervention
IV1  = "1000001"   # INTEGER PK, 直接用字面量

TODAY     = date.today()
NOW       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def dstr(d): return d.strftime("%Y-%m-%d")
def dtstr(d): return d.strftime("%Y-%m-%d %H:%M:%S")

conn = sqlite3.connect(DB)
cur  = conn.cursor()

# ── 0. 清理旧数据（幂等）────────────────────────────────────────────────────
cur.execute("DELETE FROM checkins          WHERE user_id=?",          (UID,))
cur.execute("DELETE FROM followup_tasks    WHERE plan_id=?",           (FP1,))
cur.execute("DELETE FROM followup_plans    WHERE user_id=?",           (UID,))
cur.execute("DELETE FROM alert_events      WHERE user_id=?",           (UID,))
cur.execute("DELETE FROM health_indicators WHERE user_id=?",           (UID,))
cur.execute("DELETE FROM constitution_assessments WHERE user_id=?",    (UID,))
cur.execute("DELETE FROM chronic_disease_records  WHERE user_id=?",    (UID,))
cur.execute("DELETE FROM health_profiles   WHERE user_id=?",           (UID,))
cur.execute("DELETE FROM guidance_records  WHERE patient_id=?",        (UID,))
cur.execute("DELETE FROM intervention_records WHERE recorded_by=?",    (UID,))
cur.execute("DELETE FROM interventions     WHERE patient_id=?",        (UID,))
cur.execute("DELETE FROM patient_archives  WHERE id=?",                (AID,))
cur.execute("DELETE FROM users             WHERE id=?",                (UID,))

# ── 1. 系统用户 ─────────────────────────────────────────────────────────────
from hashlib import sha256
pw_hash = "$2b$12$demohashdemohashdemo12" + "u" * 31   # 演示 hash
cur.execute("""
INSERT INTO users(id,phone,email,name,password_hash,role,is_active,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?)
""", (UID, "p_zhao_jm", None, "赵建民", pw_hash, "PATIENT", 1, NOW, NOW))

# ── 2. 患者档案 ─────────────────────────────────────────────────────────────
tags = json.dumps(["高血压", "糖尿病", "气虚质", "独居老人", "久坐:often",
                   "压力:high", "预算:low", "舌象:舌淡苔白腻", "脉象:脉沉细"],
                  ensure_ascii=False)
past = json.dumps(["HYPERTENSION", "DIABETES_T2"], ensure_ascii=False)
family = json.dumps(["父亲高血压病史", "母亲2型糖尿病病史"], ensure_ascii=False)
allergy = json.dumps(["青霉素", "磺胺类药物"], ensure_ascii=False)
cur.execute("""
INSERT INTO patient_archives(
  id, user_id, name, gender, birth_date, ethnicity, occupation,
  id_type, id_number, phone, phone2, email,
  province, city, district, address,
  emergency_contact_name, emergency_contact_phone, emergency_contact_relation,
  archive_type, tags, past_history, family_history, allergy_history, notes,
  is_deleted, created_at, updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""", (
    AID, UID, "赵建民", "male", "1962-05-18", "汉族", "退休干部",
    "ID_CARD", "32010119620518341X", "13856789012", "13700056789", None,
    "江苏省", "南京市", "鼓楼区", "鼓楼区中山路188号天隆寺小区3栋802",
    "赵丽萍", "13900056789", "子女",
    "ELDERLY", tags, past, family, allergy,
    "患有高血压合并2型糖尿病多年，气虚体质，独居，需重点随访管理",
    0, NOW, NOW
))

# ── 3. 健康档案 ─────────────────────────────────────────────────────────────
cur.execute("""
INSERT INTO health_profiles(
  id, user_id, gender, birth_date, height_cm, weight_kg, waist_cm,
  past_history, family_history, allergy_history,
  smoking, drinking, exercise_frequency, sleep_hours, stress_level,
  created_at, updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""", (
    HPID, UID, "male", "1962-05-18", 168.0, 84.0, 97.0,
    json.dumps({"conditions": ["HYPERTENSION", "DIABETES_T2"]}),
    json.dumps({"conditions": ["父亲高血压"]}),
    json.dumps({"drugs": ["青霉素", "磺胺类"], "foods": []}),
    "former", "never", "never", 5.5, "high",
    NOW, NOW
))

# ── 4. 慢病记录 ─────────────────────────────────────────────────────────────
cur.execute("""
INSERT INTO chronic_disease_records(
  id,user_id,disease_type,diagnosed_at,diagnosed_hospital,
  medications,complications,target_values,notes,is_active,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
""", (
    CD1, UID, "HYPERTENSION", "2010-03-15", "南京鼓楼医院",
    json.dumps([
        {"name":"氨氯地平","dose":"5mg","frequency":"每日一次","start_date":"2010-04-01"},
        {"name":"替米沙坦","dose":"80mg","frequency":"每日一次","start_date":"2015-07-01"},
    ], ensure_ascii=False),
    json.dumps(["左心室肥厚", "高血压肾病（早期）"], ensure_ascii=False),
    json.dumps({"systolic_target": 130, "diastolic_target": 80}),
    json.dumps({
        "summary": "血压控制欠佳，需加强监测",
        "contraindications": [
            "NSAIDs（布洛芬/双氯芬酸）—可拮抗降压效果并升压，禁用",
            "含伪麻黄碱感冒药（泰诺感冒/康泰克）—可收缩血管升压，禁用",
            "甘草制剂/复方甘草片—可致水钠潴留加重高血压，慎用",
        ]
    }, ensure_ascii=False), 1, NOW, NOW
))
cur.execute("""
INSERT INTO chronic_disease_records(
  id,user_id,disease_type,diagnosed_at,diagnosed_hospital,
  medications,complications,target_values,notes,is_active,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
""", (
    CD2, UID, "DIABETES_T2", "2018-08-20", "南京市第一医院",
    json.dumps([
        {"name":"二甲双胍","dose":"500mg","frequency":"每日两次，餐后","start_date":"2018-09-01"},
        {"name":"格列美脲","dose":"2mg","frequency":"每日一次，早餐前","start_date":"2020-01-15"},
    ], ensure_ascii=False),
    json.dumps(["周围神经病变（轻度）", "糖尿病视网膜病变（待排）"], ensure_ascii=False),
    json.dumps({"hba1c_target": 7.0, "fasting_glucose_target": 7.0}),
    json.dumps({
        "summary": "血糖波动较大，需优化方案",
        "contraindications": [
            "饮酒—格列美脲+酒精可致严重低血糖甚至昏迷，严格禁止",
            "造影检查前须停二甲双胍48h，以防造影剂肾病",
            "皮质激素（地塞米松等）—可显著升血糖，若必须使用需密切监测",
        ]
    }, ensure_ascii=False), 1, NOW, NOW
))

# ── 5. 体质评估（气虚质 已评分）─────────────────────────────────────────────
result_json = json.dumps({
    "BALANCED":          {"raw_score": 14, "converted_score": 20, "level": "no"},
    "QI_DEFICIENCY":     {"raw_score": 35, "converted_score": 82, "level": "yes"},
    "YANG_DEFICIENCY":   {"raw_score": 22, "converted_score": 44, "level": "tendency"},
    "YIN_DEFICIENCY":    {"raw_score": 18, "converted_score": 31, "level": "no"},
    "PHLEGM_DAMPNESS":   {"raw_score": 25, "converted_score": 53, "level": "tendency"},
    "DAMP_HEAT":         {"raw_score": 15, "converted_score": 22, "level": "no"},
    "BLOOD_STASIS":      {"raw_score": 20, "converted_score": 38, "level": "no"},
    "QI_STAGNATION":     {"raw_score": 17, "converted_score": 28, "level": "no"},
    "SPECIAL_DIATHESIS": {"raw_score": 13, "converted_score": 18, "level": "no"},
})
secondary = json.dumps(["YANG_DEFICIENCY", "PHLEGM_DAMPNESS"])
scored_dt = (TODAY - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
cur.execute("""
INSERT INTO constitution_assessments(
  id,user_id,status,main_type,result,secondary_types,
  submitted_at,scored_at,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?)
""", (
    CAI, UID, "SCORED", "QI_DEFICIENCY", result_json, secondary,
    scored_dt, scored_dt, scored_dt, NOW
))

# ── 6. 健康指标（90天数据，含异常值触发预警）────────────────────────────────
bp_data = [
    # (days_ago, systolic, diastolic)  含两个异常值
    (88, 148, 92), (82, 152, 94), (75, 155, 96), (68, 162, 98),   # 中度升高
    (60, 145, 90), (55, 158, 95), (48, 170, 102), (40, 165, 100), # 中度
    (33, 142, 88), (28, 186, 112), (21, 155, 97), (14, 160, 98),  # 28天前: 重度
    (7,  152, 94), (3,  148, 91), (1,  155, 96),
]
for i, (days, sys, dia) in enumerate(bp_data):
    dt = TODAY - timedelta(days=days)
    cur.execute("""
    INSERT INTO health_indicators(id,user_id,indicator_type,"values",scene,note,recorded_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        IID(f"bp{i}"), UID, "BLOOD_PRESSURE",
        json.dumps({"systolic": sys, "diastolic": dia}),
        "morning", None,
        dtstr(datetime.combine(dt, __import__("datetime").time(7, 30))), NOW, NOW
    ))

bg_data = [
    # (days_ago, value, scene)  含异常值
    (85, 7.8, "fasting"), (78, 9.2, "fasting"), (70, 11.5, "fasting"),
    (63, 8.6, "fasting"), (56, 12.3, "fasting"), (49, 9.8, "fasting"),
    (42, 10.6, "fasting"), (35, 7.5, "fasting"),
    (28, 13.9, "fasting"),  # 高值 → MEDIUM 预警
    (21, 9.4, "fasting"), (14, 11.1, "fasting"),
    (7,  8.8,  "fasting"), (3,  10.2, "postmeal_2h"), (1, 9.1, "fasting"),
]
for i, (days, val, scene) in enumerate(bg_data):
    dt = TODAY - timedelta(days=days)
    cur.execute("""
    INSERT INTO health_indicators(id,user_id,indicator_type,"values",scene,note,recorded_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        IID(f"bg{i}"), UID, "BLOOD_GLUCOSE",
        json.dumps({"value": val, "scene": scene}),
        scene, None,
        dtstr(datetime.combine(dt, __import__("datetime").time(7, 0))), NOW, NOW
    ))

weight_data = [(80, 84.2), (60, 85.0), (40, 83.8), (20, 84.5), (5, 84.0)]
for i, (days, w) in enumerate(weight_data):
    dt = TODAY - timedelta(days=days)
    cur.execute("""
    INSERT INTO health_indicators(id,user_id,indicator_type,"values",scene,note,recorded_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        IID(f"wt{i}"), UID, "WEIGHT",
        json.dumps({"value": w}), None, None,
        dtstr(datetime.combine(dt, __import__("datetime").time(8, 0))), NOW, NOW
    ))

waist_data = [(60, 97.5), (30, 98.0), (7, 97.8)]
for i, (days, w) in enumerate(waist_data):
    dt = TODAY - timedelta(days=days)
    cur.execute("""
    INSERT INTO health_indicators(id,user_id,indicator_type,"values",scene,note,recorded_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        IID(f"wc{i}"), UID, "WAIST_CIRCUMFERENCE",
        json.dumps({"value": w}), None, None,
        dtstr(datetime.combine(dt, __import__("datetime").time(8, 0))), NOW, NOW
    ))

# ── 7. 预警事件 ─────────────────────────────────────────────────────────────
# HIGH: 血压收缩压重度升高 (186 mmHg, 28天前)
RULE_HBP_H = "ef003ba84fd349229760bc67353ed958"
RULE_HBP_M = "be232e242eb2474d906ff9522e9c675e"
RULE_BG_M  = "503fc0cc610e4c3ba0b2dbf6e724fb24"
al_dt1 = (TODAY - timedelta(days=28)).strftime("%Y-%m-%d 07:30:00")
al_dt2 = (TODAY - timedelta(days=14)).strftime("%Y-%m-%d 07:00:00")
al_dt3 = (TODAY - timedelta(days=7)).strftime("%Y-%m-%d 07:30:00")

cur.execute("""
INSERT INTO alert_events(id,user_id,rule_id,severity,status,trigger_value,message,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?)
""", (AL1, UID, RULE_HBP_H, "HIGH", "OPEN",
      json.dumps({"systolic": 186, "diastolic": 112}),
      "⚠️ 危急：收缩压 186 mmHg，超过重度高血压阈值，请立即联系患者并评估用药方案。",
      al_dt1, NOW))

cur.execute("""
INSERT INTO alert_events(id,user_id,rule_id,severity,status,trigger_value,message,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?)
""", (AL2, UID, RULE_BG_M, "MEDIUM", "OPEN",
      json.dumps({"value": 13.9, "scene": "fasting"}),
      "⚠️ 提示：空腹血糖 13.9 mmol/L，明显超标，建议及时复诊，调整降糖方案。",
      al_dt2, NOW))

cur.execute("""
INSERT INTO alert_events(id,user_id,rule_id,severity,status,trigger_value,message,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?)
""", (AL3, UID, RULE_HBP_M, "MEDIUM", "ACKED",
      json.dumps({"systolic": 162, "diastolic": 98}),
      "⚠️ 提示：收缩压 162 mmHg，中度升高，请加强监测。",
      al_dt3, NOW))

# ── 8. 随访计划 + 任务 + 打卡 ────────────────────────────────────────────────
plan_start = TODAY - timedelta(days=14)
plan_end   = TODAY + timedelta(days=42)
cur.execute("""
INSERT INTO followup_plans(id,user_id,disease_type,status,start_date,end_date,note,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?)
""", (FP1, UID, "HYPERTENSION", "ACTIVE",
      dstr(plan_start), dstr(plan_end),
      "气虚质+高血压+糖尿病综合随访，每3天血压监测，每周血糖监测", NOW, NOW))

# 生成任务和打卡记录
task_defs = []
# 过去14天：每3天血压任务，2次血糖，2次服药
for d in range(14, 0, -3):
    task_defs.append((TODAY - timedelta(days=d), "INDICATOR_REPORT", "血压监测", '{"indicator_type":"BLOOD_PRESSURE"}'))
for d in [12, 5]:
    task_defs.append((TODAY - timedelta(days=d), "INDICATOR_REPORT", "空腹血糖", '{"indicator_type":"BLOOD_GLUCOSE"}'))
for d in [13, 10, 7, 4, 1]:
    task_defs.append((TODAY - timedelta(days=d), "MEDICATION",       "服用降压药", '{}'))
# 今天
task_defs.append((TODAY, "INDICATOR_REPORT", "今日血压监测", '{"indicator_type":"BLOOD_PRESSURE"}'))
task_defs.append((TODAY, "MEDICATION",       "服用降糖药", '{}'))
# 未来
for d in [3, 6, 9, 14, 21, 28, 35, 42]:
    task_defs.append((TODAY + timedelta(days=d), "INDICATOR_REPORT", "血压监测", '{"indicator_type":"BLOOD_PRESSURE"}'))
for d in [7, 14, 21, 28]:
    task_defs.append((TODAY + timedelta(days=d), "INDICATOR_REPORT", "空腹血糖", '{"indicator_type":"BLOOD_GLUCOSE"}'))
for d in [3, 6, 9, 12, 15, 18, 21, 24, 27, 30]:
    task_defs.append((TODAY + timedelta(days=d), "EXERCISE", "有氧散步30分钟", '{}'))

for i, (tdate, ttype, tname, tmeta) in enumerate(task_defs):
    tid = TID(i)
    cur.execute("""
    INSERT INTO followup_tasks(id,plan_id,task_type,name,scheduled_date,required,meta,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (tid, FP1, ttype, tname, dstr(tdate), 1, tmeta, NOW, NOW))
    # 过去任务 → 生成打卡
    if tdate < TODAY:
        import random; random.seed(i)
        status = "DONE" if random.random() > 0.45 else "MISSED"
        if status == "DONE":
            if ttype == "INDICATOR_REPORT" and "BLOOD_PRESSURE" in tmeta:
                val = json.dumps({"systolic": random.randint(145, 172), "diastolic": random.randint(88, 102)})
            elif ttype == "INDICATOR_REPORT":
                val = json.dumps({"value": round(random.uniform(8.0, 13.5), 1), "scene": "fasting"})
            else:
                val = json.dumps({"done": True})
            cur.execute("""
            INSERT INTO checkins(id,task_id,user_id,status,value,note,checked_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """, (CID(i), tid, UID, "DONE", val, None,
                  dtstr(datetime.combine(tdate, __import__("datetime").time(8, 0))), NOW, NOW))
        else:
            cur.execute("""
            INSERT INTO checkins(id,task_id,user_id,status,value,note,checked_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """, (CID(i), tid, UID, "MISSED", None, None, None, NOW, NOW))

# ── 9. 指导方案 ─────────────────────────────────────────────────────────────
# 当前方案（PUBLISHED = 已生效）
plan_content_pub = """# 气虚质+高血压综合调理方案

## 作息建议
22:30 前入睡，保证 7 小时睡眠；午间小憩 20 分钟；避免熬夜耗气。

## 饮食/食疗
低盐低脂，每日食盐 <5g；
推荐：黄芪红枣粥（补气）、山药薏仁汤（健脾祛湿）；
忌辛辣刺激、生冷寒凉；忌过度饮酒。

## 运动建议
每日晨间散步 20-30 分钟；
推荐八段锦、太极拳，每周 3 次；
避免剧烈运动，以不疲劳为度。

## 情志建议
保持心情舒畅，避免情绪激动；
每日 5 分钟正念呼吸；建议家人多陪伴。

## 穴位/艾灸
艾灸足三里、气海、关元，每次 15 分钟，每周 3 次；
按揉合谷、太冲，每次各 3 分钟。

## 到院项目
每月 1 次中医体质调理推拿；
建议参加院内气虚质健康管理小组（每季度）。

## 复评节点
随访：14天后
目标：血压 <140/90 mmHg，空腹血糖 <8.0 mmol/L"""

cur.execute("""
INSERT INTO guidance_records(id,patient_id,doctor_id,guidance_type,title,content,status,is_read,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?,?)
""", (
    GR2, UID, DOCTOR_ID, "GUIDANCE",
    "气虚质+高血压综合调理方案（2026-02-20）",
    plan_content_pub, "PUBLISHED", 1,
    (TODAY - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S"), NOW
))

# 草稿方案
plan_content_draft = """# 气虚质+高血压+糖尿病三病共管强化方案（草稿）

## 作息建议
21:30 前入睡，保证 7.5 小时睡眠；严格作息规律，避免熬夜。

## 饮食/食疗
糖尿病饮食：少食多餐，每日主食控制在 200g；
推荐：黄芪炖鸡汤、人参泡水代茶；
忌高糖高盐高脂；记录每日饮食日记。

## 运动建议
餐后 30 分钟散步 15 分钟；
每周 3 次有氧运动（强度：微微出汗为度）；
监测运动前后血糖，防止低血糖。

## 情志建议
认知行为疗法：识别负面思维，重建积极认知；每周参加病友互助群。

## 穴位/艾灸
艾灸足三里、脾俞、胃俞，补气健脾；
每次 20 分钟，每周 4 次。

## 到院项目
每半月 1 次中医调理（针灸+推拿结合）；血压血糖每月复查。

## 复评节点
随访：14天后
目标：血压 <135/85 mmHg，空腹血糖 <7.5 mmol/L，HbA1c <7.5%"""

cur.execute("""
INSERT INTO guidance_records(id,patient_id,doctor_id,guidance_type,title,content,status,is_read,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?,?)
""", (
    GR1, UID, DOCTOR_ID, "GUIDANCE",
    "气虚质+高血压+糖尿病三病共管强化方案（草稿）",
    plan_content_draft, "DRAFT", 0,
    (TODAY - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), NOW
))

# ── 10. 干预记录 ─────────────────────────────────────────────────────────────
cur.execute("""
INSERT INTO interventions(
  patient_id,plan_name,intervention_type,target_constitution,goal,
  content_detail,precaution,executor_id,start_date,duration_weeks,
  frequency,status,created_by,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""", (
    UID, "气虚体质中医调理疗程", "中医推拿", "QI_DEFICIENCY",
    "改善气虚症状，提高免疫力，辅助降压控糖",
    "以补气健脾为主，每次推拿重点穴位：足三里、气海、脾俞、胃俞",
    "血压 >180/110 时暂停，低血糖发作时立即停止",
    DOCTOR_ID,
    dstr(TODAY - timedelta(days=14)), 8, "每周2次",
    "IN_PROGRESS", DOCTOR_ID, NOW, NOW
))
iv_id = cur.lastrowid
for s, (days, eff, feedback) in enumerate([
    (13, "有效",   "推拿后感觉轻松，睡眠略有改善"),
    (10, "有效",   "血压较上次稍降，精神稍好"),
    (7,  "显效",   "今日血压140/88，患者反映精力明显提升"),
    (4,  "有效",   "坚持散步，症状改善"),
    (1,  "有效",   "患者依从性良好，下次重点加强饮食干预"),
], 1):
    dt = (TODAY - timedelta(days=days)).strftime("%Y-%m-%d 10:00:00")
    cur.execute("""
    INSERT INTO intervention_records(intervention_id,session_no,executed_at,effectiveness,patient_feedback,notes,recorded_by,created_at)
    VALUES(?,?,?,?,?,?,?,?)
    """, (iv_id, s, dt, eff, feedback, "操作规范，患者配合良好", UID, dt))

conn.commit()
conn.close()

# ── 输出摘要 ─────────────────────────────────────────────────────────────────
print("=" * 56)
print("赵建民 全量数据种子完成")
print("=" * 56)
print(f"  档案 ID : {AID}")
print(f"  用户 ID : {UID}")
print(f"  手机号  : 13856789012")
print(f"  体质    : 气虚质（QI_DEFICIENCY）")
print(f"  慢病    : 高血压 + 2型糖尿病")
print(f"  过敏史  : 青霉素、磺胺类")
print(f"  指标    : {len(bp_data)}条血压 / {len(bg_data)}条血糖 / {len(weight_data)}条体重 / {len(waist_data)}条腰围")
print(f"  预警    : 2条OPEN（HIGH血压 + MEDIUM血糖）+ 1条ACKED")
print(f"  随访计划: ACTIVE（{dstr(plan_start)} ~ {dstr(plan_end)}）")
print(f"  任务数  : {len(task_defs)}条（含今日任务）")
print(f"  草稿方案: {GR1[:8]}... 《气虚质+高血压+糖尿病三病共管强化方案》")
print(f"  当前方案: {GR2[:8]}... 《气虚质+高血压综合调理方案（2026-02-20）》")
print(f"  干预记录: 5次推拿记录")
print()
print("插件搜索方式：手机号 13856789012 或姓名 赵建民")
