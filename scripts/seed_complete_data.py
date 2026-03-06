"""
完整演示数据补充脚本 v1.0
===========================
功能：
1. 为所有未绑定 user_id 的档案创建 PATIENT 用户并关联
2. 为所有绑定用户补充 HealthProfile（体重/身高/BMI/生活方式）
3. 为所有绑定用户补充 ConstitutionAssessment（体质评估）
4. 为老年/重点人群患者补充 ChronicDiseaseRecord（慢病记录）
5. 为所有绑定用户补充 HealthIndicator（血压/血糖/体重，近90天）
6. 为所有绑定用户补充 GuidanceRecord（调理方案，PUBLISHED + DRAFT）
7. 补充更多 GuidanceTemplate（方案模板）
8. 补充 AlertEvent（预警事件）
9. 为未建随访计划的患者创建 FollowupPlan + FollowupTask

运行方式（在项目根目录）：
    python scripts/seed_complete_data.py

幂等：大多数补充操作先检查是否已存在再插入。
"""
import json
import os
import random
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 使用 passlib 生成密码哈希（与项目一致）
try:
    from passlib.context import CryptContext
    _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    DEFAULT_PW_HASH = _pwd_ctx.hash("Demo@123456")
except Exception:
    # 兜底：使用预计算的哈希（Demo@123456）
    DEFAULT_PW_HASH = "$2b$12$8bkAT1k.qy7xFQCnnbqTheEisCkOFTrCX9DkR.kfvnEFOCGiUm7iC"

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo.db")

random.seed(42)  # 可复现

# ── 常量 ──────────────────────────────────────────────────────────────────────

BODY_TYPES = [
    "BALANCED", "QI_DEFICIENCY", "YANG_DEFICIENCY", "YIN_DEFICIENCY",
    "PHLEGM_DAMPNESS", "DAMP_HEAT", "BLOOD_STASIS", "QI_STAGNATION", "SPECIAL_DIATHESIS"
]
BODY_TYPE_BY_ARCHIVE = {
    "ELDERLY": ["QI_DEFICIENCY", "YANG_DEFICIENCY", "PHLEGM_DAMPNESS", "BLOOD_STASIS", "YIN_DEFICIENCY"],
    "CHILD":   ["BALANCED", "QI_DEFICIENCY", "SPECIAL_DIATHESIS"],
    "FEMALE":  ["QI_STAGNATION", "BLOOD_STASIS", "YIN_DEFICIENCY", "BALANCED", "QI_DEFICIENCY"],
    "KEY_FOCUS": ["PHLEGM_DAMPNESS", "DAMP_HEAT", "BLOOD_STASIS", "QI_DEFICIENCY"],
    "NORMAL":  ["BALANCED", "QI_DEFICIENCY", "DAMP_HEAT", "QI_STAGNATION"],
}

DISEASE_MESSAGES = {
    "HYPERTENSION": [
        "血压收缩压 {val} mmHg，超过目标值130 mmHg",
        "连续3次测量收缩压均超过140 mmHg，提示血压控制不佳",
        "血压偏高，建议调整降压方案",
    ],
    "DIABETES_T2": [
        "空腹血糖 {val} mmol/L，超过正常上限7.0 mmol/L",
        "餐后2小时血糖异常升高，需关注",
        "血糖波动较大，提示糖尿病控制欠佳",
    ],
}

# 调理方案模板内容
PLAN_CONTENTS = [
    """\
## 高血压中医调理方案

### 中医辨证
患者证属肝阳上亢，兼夹痰湿，治以平肝熄风、化痰通络。

### 中药调理
- 天麻钩藤饮加减：天麻12g、钩藤15g（后下）、石决明30g（先煎）、
  牛膝12g、黄芩10g、栀子10g、茯神12g
- 每日1剂，水煎服，分2次温服

### 饮食指导
- 低盐饮食：每日食盐 < 5g
- 减少高脂、油腻食物摄入
- 宜食：芹菜、菠菜、苦瓜、荷叶茶
- 禁忌：浓茶、咖啡、烟酒

### 生活调摄
- 保持情绪稳定，避免情绪激动
- 规律作息，晚10点前入睡
- 每天散步30分钟，避免剧烈运动

### 随访要求
- 每日晨起测量血压并记录
- 1个月后复诊
""",
    """\
## 2型糖尿病中医综合管理方案

### 中医辨证
气阴两虚，兼有瘀血，治以益气养阴、活血化瘀。

### 中药调理
- 玉液汤合参芪地黄汤加减：
  黄芪30g、山药30g、葛根15g、麦冬12g、
  知母10g、天花粉15g、五味子10g、生地黄15g
- 水煎服，每日2次

### 饮食控制
- 控制总热量，少量多餐（每日5-6餐）
- 主食优先选择粗粮：燕麦、糙米、荞麦
- 多食绿叶蔬菜，每日蔬菜 ≥ 500g
- 禁食糖果、甜饮料、精制糕点

### 运动处方
- 每餐后30分钟进行20-30分钟中等强度步行
- 每周3-5次抗阻训练

### 监测要求
- 每日监测空腹及餐后2h血糖
- 每3个月检测HbA1c
- 2周后复诊评估
""",
    """\
## 气虚质中医调理方案

### 体质特征
气虚质患者常见疲倦乏力、气短懒言、容易感冒、自汗。

### 中药调理
- 补中益气汤加减：
  黄芪20g、白术12g、陈皮10g、升麻6g、柴胡6g、
  党参15g、当归10g、炙甘草6g
- 每日1剂，分2次温服

### 食疗推荐
- 黄芪粥：黄芪30g煎水，加大米100g煮粥，每日早餐
- 红枣枸杞茶：每日代茶饮
- 宜食：山药、大枣、龙眼、鸡肉、牛肉
- 少食：生冷、油腻、辛辣食物

### 生活调节
- 避免过度劳累，合理安排工作与休息
- 适当晒太阳，以补充阳气
- 八段锦、太极拳等缓和运动，每次20-30分钟

### 注意事项
- 感冒时暂停补益类中药
- 定期复查，调整方案
""",
    """\
## 痰湿质综合干预方案

### 体质辨识
痰湿质特征：形体肥胖、腹部松软、口黏腻、舌苔白腻、脉滑。

### 化痰祛湿中药
- 二陈汤合平胃散加减：
  半夏10g、陈皮12g、茯苓15g、苍术12g、
  厚朴10g、薏苡仁30g、荷叶15g、决明子15g
- 每日1剂

### 饮食原则
- 控制总热量，避免过饱
- 少食肥甘厚味：肥肉、油炸食品、甜食
- 宜食：薏苡仁、冬瓜、萝卜、海带
- 多饮温水，少饮冷饮

### 运动方案
- 有氧运动为主：快走、游泳、骑车
- 每日运动时间 ≥ 40分钟
- 微微出汗为宜，切勿大汗淋漓

### 体重管理
- 目标：3个月内体重减少3-5%
- 每周称重记录1次
""",
    """\
## 老年慢病综合调理方案

### 综合评估
患者年龄偏大，多病共存，需整体调摄，标本兼治。

### 中医治则
扶正固本为主，活血通络为辅。

### 中药处方
- 生脉散合六味地黄丸加减：
  人参10g（另煎兑入）、麦冬15g、五味子10g、
  熟地黄20g、山药15g、山茱萸12g、丹皮10g、
  泽泻12g、茯苓15g
- 每日1剂，慢火水煎

### 生活指导
- 定时定量三餐，细嚼慢咽
- 睡前用温水泡脚20分钟，加入艾叶、花椒
- 每日做穴位按摩：足三里、三阴交、涌泉穴

### 安全注意
- 如出现头晕、胸闷立即就医
- 坚持按时服用西药，中西医结合
- 家属陪同复诊

### 随访计划
- 每2周门诊复诊
- 每日记录血压、血糖数据
""",
]

DRAFT_CONTENTS = [
    "## 方案草稿\n\n根据最新检查结果，拟调整如下：\n- 调整用药剂量\n- 增加运动处方\n- 饮食改进建议\n（待完善）",
    "## 初步方案\n\n根据体质辨识结果，患者体质偏颇，建议：\n1. 中药调理（方案待定）\n2. 饮食调整\n3. 生活方式改善\n（草稿，需复诊确认）",
    "## 调整方案（草稿）\n\n前次方案执行情况：血压/血糖有所改善，但仍需加强。\n调整要点：\n- 增加黄芪用量至30g\n- 加强饮食控制\n（待确认后发布）",
]

# 更多指导模板
EXTRA_TEMPLATES = [
    {
        "name": "阴虚体质中医调理方案",
        "guidance_type": "GUIDANCE",
        "scope": "PERSONAL",
        "tags": "阴虚,滋阴,养阴",
        "content": """\
## 阴虚质中医调理方案

### 体质特征
阴虚质：形体偏瘦，口干、手足心热、盗汗、便干，舌红少苔，脉细数。

### 滋阴中药
- 六味地黄丸加减（汤剂）：
  熟地黄20g、山药15g、山茱萸12g、丹皮10g、泽泻12g、茯苓15g
  加：麦冬15g、北沙参12g、枸杞子15g
- 每日1剂，分2次温服

### 食疗
- 银耳莲子百合汤：滋阴润肺
- 桑椹枸杞粥：补肾益精
- 宜食：梨、荸荠、甘蔗、绿豆、黑芝麻
- 忌食：辛辣、烧烤、浓茶、咖啡

### 生活调养
- 保证睡眠7-8小时，忌熬夜
- 避免剧烈运动大量出汗
- 适合游泳、练习瑜伽

### 随访
- 1个月后复诊
""",
    },
    {
        "name": "血瘀质中医调理方案",
        "guidance_type": "GUIDANCE",
        "scope": "PERSONAL",
        "tags": "血瘀,活血,化瘀",
        "content": """\
## 血瘀质中医调理方案

### 体质特征
血瘀质：面色晦暗，易出现瘀斑，肌肤甲错，舌质紫暗或有瘀点，脉涩。

### 活血化瘀中药
- 桃红四物汤加减：
  桃仁12g、红花10g、当归12g、川芎10g、
  熟地黄15g、白芍12g、丹参15g、郁金12g
- 水煎服，每日2次

### 食疗
- 宜食：山楂、黑木耳、玫瑰花茶、藏红花泡水
- 适量饮用红酒（< 50ml/日，不饮酒者不建议）
- 避免寒凉食物

### 运动
- 中等强度有氧运动：快走、跑步、骑车
- 每次运动使身体微微发热出汗
- 避免久坐

### 注意事项
- 月经期间暂停活血药物
- 如有出血倾向，立即停药并就诊
""",
    },
    {
        "name": "气郁质中医调理方案",
        "guidance_type": "GUIDANCE",
        "scope": "PERSONAL",
        "tags": "气郁,疏肝,理气",
        "content": """\
## 气郁质中医调理方案

### 体质特征
气郁质：情绪低落、多愁善感、容易焦虑紧张，胸胁胀闷，善太息，舌淡苔薄，脉弦。

### 疏肝理气中药
- 柴胡疏肝散加减：
  柴胡12g、白芍15g、川芎10g、枳壳10g、
  陈皮12g、香附12g、郁金12g、合欢皮15g
- 每日1剂，分2次温服

### 心理调摄
- 规律参加社交活动，拓展兴趣爱好
- 练习正念冥想，每日10-15分钟
- 保持乐观情绪，积极面对生活

### 食疗推荐
- 玫瑰花茶、茉莉花茶：疏肝解郁
- 宜食：佛手、橘皮、萝卜、芹菜
- 少食：酸涩收敛食物

### 运动
- 户外运动为主，多接触大自然
- 太极拳、八段锦、瑜伽

### 注意事项
- 避免长时间独处
- 如出现明显焦虑、抑郁症状，建议心理科就诊
""",
    },
    {
        "name": "儿童保健中医指导方案",
        "guidance_type": "GUIDANCE",
        "scope": "PERSONAL",
        "tags": "儿童,保健,脾胃",
        "content": """\
## 儿童中医保健指导方案

### 中医调理原则
小儿脏腑娇嫩，形气未充，调理以健脾益肺为主，兼顾安神助眠。

### 小儿推拿（家长操作）
每日晨起或睡前，各操作一次：
- 补脾经：拇指指腹沿大鱼际推300次
- 揉中脘：以肚脐为中心顺时针按揉200次
- 捏脊：自尾骨至大椎穴，捏拿3-5遍
- 揉足三里：每侧各100次

### 饮食调养
- 饮食规律，定时定量，切勿过饱
- 少食生冷、油腻、甜食
- 宜食：小米粥、山药粥、大枣（去核）
- 避免零食替代正餐

### 睡眠与运动
- 保证充足睡眠（学龄儿童9-10小时）
- 户外活动每日 ≥ 1小时
- 减少电子产品使用时间

### 季节调护
- 换季时注意保暖，尤其腹部
- 流感季节可艾灸足三里预防
""",
    },
    {
        "name": "女性月经不调中医调理方案",
        "guidance_type": "GUIDANCE",
        "scope": "PERSONAL",
        "tags": "女性,月经,气血",
        "content": """\
## 女性月经不调中医调理方案

### 中医辨证
气血不足，冲任失调，治以补气养血、调和冲任。

### 中药调理
- 八珍汤加减：
  人参10g（另煎）、白术12g、茯苓15g、炙甘草6g、
  当归15g、白芍12g、川芎10g、熟地黄20g、
  加：阿胶10g（烊化）、艾叶10g
- 月经前1周开始服用，连服14天

### 饮食
- 经前经期忌生冷、寒凉食物
- 宜食：红糖姜茶、红枣、桂圆、黑豆、猪血
- 补铁：动物肝脏（每周2次）、菠菜

### 艾灸穴位（月经前一周）
- 关元穴、三阴交、足三里
- 每次灸20-30分钟，以局部温热为度

### 生活调摄
- 避免寒冷刺激：热水泡脚、注意腹部保暖
- 保持情绪稳定
- 适度休息，避免过劳

### 复诊计划
- 连续3个月经周期后复诊评估
""",
    },
    {
        "name": "老年骨质疏松预防方案",
        "guidance_type": "GUIDANCE",
        "scope": "GROUP",
        "tags": "老年,骨质疏松,补肾",
        "content": """\
## 老年骨质疏松中医预防调理方案

### 中医认识
肾主骨，骨质疏松与肾虚密切相关，治以补肾壮骨、强筋健骨。

### 补肾壮骨中药
- 六味地黄丸合左归丸加减：
  熟地黄20g、龟板15g（先煎）、鹿角胶10g（烊化）、
  山药15g、山茱萸12g、枸杞子15g、菟丝子15g、杜仲12g
- 每日1剂，长期服用

### 补钙食疗
- 每日饮奶300-400ml（低脂牛奶/酸奶）
- 豆腐、虾皮、海带等富钙食物
- 小鱼干（连骨吃）

### 运动处方
- 负重运动：每日步行30-40分钟
- 平衡训练：单脚站立、八段锦
- 避免跌倒：去除家中危险因素

### 日照
- 每日户外日照20-30分钟（避免正午强光）
- 促进维生素D合成，有助钙吸收

### 监测
- 每年骨密度检查1次
- 3个月复诊
""",
    },
    {
        "name": "慢性阻塞性肺病中医辅助方案",
        "guidance_type": "GUIDANCE",
        "scope": "GROUP",
        "tags": "慢阻肺,肺肾两虚,补益",
        "content": """\
## COPD 中医辅助调理方案

### 中医辨证
久病及肾，肺肾两虚，痰瘀互结，治以补肺益肾、化痰活血。

### 中药调理
- 补肺汤合参蛤散加减：
  人参10g（另煎）、黄芪30g、熟地黄15g、五味子10g、
  紫菀12g、桑白皮12g、款冬花12g、蛤蚧1对（研粉冲服）
- 稳定期长期服用

### 呼吸训练
- 缩唇呼吸：每日3次，每次10分钟
- 腹式呼吸：仰卧位深呼吸练习
- 肺康复操（见附件）

### 氧疗配合
- 长期家庭氧疗（遵医嘱）
- 氧流量1-2 L/min，每日≥15小时

### 饮食
- 高蛋白、高维生素饮食
- 少量多餐，避免过饱影响呼吸
- 戒烟（最重要）

### 注意事项
- 预防感冒：接种流感疫苗
- 急性加重立即就医
""",
    },
    {
        "name": "高血压随访指导（标准版）",
        "guidance_type": "GUIDANCE",
        "scope": "GROUP",
        "tags": "高血压,随访,标准",
        "content": """\
## 高血压随访标准指导

### 血压监测要求
- 家庭自测血压：每日晨起、睡前各测1次
- 记录收缩压/舒张压及心率
- 血压 > 180/110 mmHg 立即就医

### 用药指导
- 按时按量服用降压药，切勿自行停药
- 如出现头晕、心慌等不适立即告知医生

### 生活方式干预
- 减盐：每日食盐 < 5g（避免酱油、腌制食品）
- 减重：每周体重下降 0.5-1kg 为宜
- 戒烟限酒
- 规律运动：每周 ≥ 150分钟中等强度有氧运动

### 复诊时间
- 血压达标：每3个月复诊
- 血压未达标：每月复诊
- 如有特殊情况随时就诊
""",
    },
]


def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def uid():
    return uuid.uuid4().hex  # 32位不带连字符


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


def date_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ── 主体 ──────────────────────────────────────────────────────────────────────

def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    # ─ 取管理员/医生 ID（用于创建方案/预警）
    admin_row = c.execute("SELECT id FROM users WHERE role='ADMIN' LIMIT 1").fetchone()
    doctor_row = c.execute("SELECT id FROM users WHERE role='PROFESSIONAL' LIMIT 1").fetchone()
    admin_id  = admin_row[0] if admin_row else None
    doctor_id = doctor_row[0] if doctor_row else None

    # ─ 取现有 alert_rules
    rule_rows = c.execute("SELECT id, name FROM alert_rules LIMIT 6").fetchall()
    rule_ids = [r[0] for r in rule_rows]

    stats = {
        "users_created": 0,
        "profiles_created": 0,
        "constitutions_created": 0,
        "diseases_created": 0,
        "indicators_created": 0,
        "plans_created": 0,
        "drafts_created": 0,
        "templates_created": 0,
        "alerts_created": 0,
        "followup_plans_created": 0,
        "followup_tasks_created": 0,
    }

    # ══════════════════════════════════════════════════════════════════════════
    # 1. 为未绑定 user_id 的档案创建 PATIENT 用户
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[1] 处理未绑定 user_id 的患者档案...")

    unlinked = c.execute("""
        SELECT id, name, archive_type, phone, birth_date, gender
        FROM patient_archives
        WHERE is_deleted=0
          AND user_id IS NULL
          AND name NOT IN ('test','1','测试','Test')
          AND name IS NOT NULL
          AND length(name) >= 2
        ORDER BY archive_type, name
        LIMIT 60
    """).fetchall()

    for row in unlinked:
        archive_id, name, archive_type, phone, birth_date, gender = row

        # 如果 phone 为空或已被占用，生成一个虚拟 phone
        if not phone or len(phone) < 8:
            phone = f"1{random.randint(30,99)}{random.randint(10000000,99999999)}"

        # 检查 phone 是否已被用户使用
        existing_user = c.execute(
            "SELECT id FROM users WHERE phone=?", (phone,)
        ).fetchone()
        if existing_user:
            # 已有用户，直接关联
            user_id = existing_user[0]
            # 检查该 user_id 是否已关联其他档案
            conflict = c.execute(
                "SELECT id FROM patient_archives WHERE user_id=? AND id!=?",
                (user_id, archive_id)
            ).fetchone()
            if conflict:
                # 冲突，用新 phone
                phone = f"1{random.randint(30,99)}{random.randint(10000000,99999999)}"
                existing_user = None

        if not existing_user:
            email = f"p_{archive_id[:8]}@demo.tcm"
            user_id = uid()
            try:
                c.execute("""
                    INSERT INTO users (id, phone, email, name, password_hash, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'PATIENT', 1, ?, ?)
                """, (user_id, phone, email, name, DEFAULT_PW_HASH, now_str(), now_str()))
                stats["users_created"] += 1
            except sqlite3.IntegrityError:
                # phone 冲突，用新 phone
                phone2 = f"1{random.randint(30,99)}{random.randint(10000000,99999999)}"
                email2 = f"p2_{archive_id[:6]}@demo.tcm"
                try:
                    c.execute("""
                        INSERT INTO users (id, phone, email, name, password_hash, role, is_active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'PATIENT', 1, ?, ?)
                    """, (user_id, phone2, email2, name, DEFAULT_PW_HASH, now_str(), now_str()))
                    stats["users_created"] += 1
                except sqlite3.IntegrityError:
                    continue  # 跳过无法创建的用户

        # 关联 archive
        c.execute("UPDATE patient_archives SET user_id=? WHERE id=?", (user_id, archive_id))

    conn.commit()
    print(f"    新建用户: {stats['users_created']} 个")

    # ══════════════════════════════════════════════════════════════════════════
    # 2. 获取所有已绑定的患者（archive + user）
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[2] 读取所有已绑定患者档案...")

    patients = c.execute("""
        SELECT a.id, a.user_id, a.name, a.archive_type, a.birth_date, a.gender,
               a.past_history, a.family_history, a.allergy_history, a.tags
        FROM patient_archives a
        WHERE a.is_deleted=0 AND a.user_id IS NOT NULL
        ORDER BY a.archive_type, a.name
    """).fetchall()
    print(f"    共 {len(patients)} 位患者可操作")

    for row in patients:
        (archive_id, user_id, name, archive_type,
         birth_date, gender, past_history_raw,
         family_history_raw, allergy_history_raw, tags_raw) = row

        def _load_list(raw):
            if not raw:
                return []
            try:
                v = json.loads(raw)
                if isinstance(v, list):
                    return [str(x) for x in v]
                return [str(v)]
            except Exception:
                return []

        tags = _load_list(tags_raw)
        past_history = _load_list(past_history_raw)
        family_history = _load_list(family_history_raw)
        allergy_history = _load_list(allergy_history_raw)

        atype = archive_type or "NORMAL"

        # ── 2a. HealthProfile ────────────────────────────────────────────
        existing_hp = c.execute(
            "SELECT id FROM health_profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        if not existing_hp:
            if atype == "CHILD":
                height = round(random.uniform(100, 155), 1)
                weight = round(random.uniform(18, 45), 1)
            elif atype == "ELDERLY":
                height = round(random.uniform(155, 175), 1)
                weight = round(random.uniform(55, 85), 1)
            elif atype == "FEMALE":
                height = round(random.uniform(155, 168), 1)
                weight = round(random.uniform(48, 72), 1)
            else:
                height = round(random.uniform(160, 180), 1)
                weight = round(random.uniform(55, 90), 1)
            waist = round(weight * 0.55 + random.uniform(-5, 10), 1)

            smoking_choices = (
                ["never", "never", "former"] if atype in ("FEMALE", "CHILD")
                else ["never", "former", "current", "never"]
            )
            drinking_choices = (
                ["never", "never", "occasional"] if atype in ("FEMALE", "CHILD")
                else ["never", "occasional", "former", "current"]
            )
            exercise_choices = ["never", "occasional", "regular", "occasional"]

            c.execute("""
                INSERT INTO health_profiles
                  (id, user_id, gender, birth_date, height_cm, weight_kg, waist_cm,
                   past_history, family_history, allergy_history,
                   smoking, drinking, exercise_frequency, sleep_hours, stress_level,
                   created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid(), user_id,
                gender or ("female" if atype == "FEMALE" else "male"),
                birth_date,
                height, weight, waist,
                json.dumps(past_history, ensure_ascii=False),
                json.dumps(family_history, ensure_ascii=False),
                json.dumps(allergy_history, ensure_ascii=False),
                random.choice(smoking_choices),
                random.choice(drinking_choices),
                random.choice(exercise_choices),
                round(random.uniform(5.5, 8.5), 1),
                random.choice(["low", "medium", "medium", "high"]),
                now_str(), now_str()
            ))
            stats["profiles_created"] += 1

        # ── 2b. ConstitutionAssessment ────────────────────────────────────
        existing_ca = c.execute(
            "SELECT id FROM constitution_assessments WHERE user_id=?", (user_id,)
        ).fetchone()
        if not existing_ca:
            body_type_pool = BODY_TYPE_BY_ARCHIVE.get(atype, BODY_TYPES)
            main_type = random.choice(body_type_pool)

            # 找出3个次要体质
            secondary = random.sample(
                [b for b in BODY_TYPES if b != main_type],
                min(3, len(BODY_TYPES) - 1)
            )
            scored_ago = random.randint(30, 180)

            c.execute("""
                INSERT INTO constitution_assessments
                  (id, user_id, status, main_type, result, secondary_types,
                   submitted_at, scored_at, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                uid(), user_id, "SCORED", main_type,
                json.dumps({"main_score": random.randint(60, 95)}, ensure_ascii=False),
                json.dumps(secondary, ensure_ascii=False),
                days_ago(scored_ago + 1), days_ago(scored_ago),
                days_ago(scored_ago + 1), days_ago(scored_ago)
            ))
            stats["constitutions_created"] += 1

        # ── 2c. ChronicDiseaseRecord ──────────────────────────────────────
        has_hypertension = any(k in "".join(tags + past_history) for k in ["高血压", "血压"])
        has_diabetes = any(k in "".join(tags + past_history) for k in ["糖尿病", "血糖"])

        # 老年/重点人群随机补充慢病
        if atype in ("ELDERLY", "KEY_FOCUS") and not has_hypertension and random.random() < 0.6:
            has_hypertension = True
        if atype in ("ELDERLY", "KEY_FOCUS") and not has_diabetes and random.random() < 0.35:
            has_diabetes = True

        if has_hypertension:
            existing = c.execute(
                "SELECT id FROM chronic_disease_records WHERE user_id=? AND disease_type='HYPERTENSION'",
                (user_id,)
            ).fetchone()
            if not existing:
                diag_years_ago = random.randint(1, 10)
                c.execute("""
                    INSERT INTO chronic_disease_records
                      (id, user_id, disease_type, diagnosed_at, diagnosed_hospital,
                       medications, complications, target_values, notes, is_active,
                       created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), user_id, "HYPERTENSION",
                    date_ago(diag_years_ago * 365),
                    random.choice(["北京协和医院", "北京人民医院", "北京朝阳医院", "当地社区卫生中心"]),
                    json.dumps([
                        {"name": random.choice(["氨氯地平", "缬沙坦", "硝苯地平缓释片"]),
                         "dose": "5mg", "frequency": "每日1次"}
                    ], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps({"systolic_target": 130, "diastolic_target": 80}, ensure_ascii=False),
                    "规律服药，需长期监测",
                    1, now_str(), now_str()
                ))
                stats["diseases_created"] += 1

        if has_diabetes:
            existing = c.execute(
                "SELECT id FROM chronic_disease_records WHERE user_id=? AND disease_type='DIABETES_T2'",
                (user_id,)
            ).fetchone()
            if not existing:
                diag_years_ago = random.randint(1, 8)
                c.execute("""
                    INSERT INTO chronic_disease_records
                      (id, user_id, disease_type, diagnosed_at, diagnosed_hospital,
                       medications, complications, target_values, notes, is_active,
                       created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), user_id, "DIABETES_T2",
                    date_ago(diag_years_ago * 365),
                    random.choice(["北京协和医院", "北京人民医院", "北京友谊医院"]),
                    json.dumps([
                        {"name": random.choice(["二甲双胍", "格列齐特", "达格列净"]),
                         "dose": "500mg", "frequency": "每日2次，餐后"}
                    ], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps({"hba1c_target": 7.0, "fasting_glucose_target": 7.0}, ensure_ascii=False),
                    "饮食控制+药物治疗",
                    1, now_str(), now_str()
                ))
                stats["diseases_created"] += 1

        # ── 2d. HealthIndicator（近90天时序数据）──────────────────────────
        existing_ind_count = c.execute(
            "SELECT COUNT(*) FROM health_indicators WHERE user_id=?", (user_id,)
        ).fetchone()[0]

        if existing_ind_count < 4:
            # 按病情生成血压数据（每10-14天一条，共6-8条）
            if has_hypertension or atype == "ELDERLY":
                for i in range(random.randint(5, 9)):
                    days = random.randint(3, 88)
                    if has_hypertension:
                        systolic = random.randint(125, 165)
                        diastolic = random.randint(78, 100)
                    else:
                        systolic = random.randint(110, 140)
                        diastolic = random.randint(65, 90)
                    c.execute("""
                        INSERT INTO health_indicators
                          (id, user_id, indicator_type, "values", scene, note, recorded_at, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (
                        uid(), user_id, "BLOOD_PRESSURE",
                        json.dumps({"systolic": systolic, "diastolic": diastolic}),
                        "morning", "晨起测量",
                        days_ago(days), days_ago(days), days_ago(days)
                    ))
                    stats["indicators_created"] += 1

            # 血糖数据
            if has_diabetes or random.random() < 0.3:
                for i in range(random.randint(4, 8)):
                    days = random.randint(3, 88)
                    if has_diabetes:
                        glucose = round(random.uniform(5.5, 12.0), 1)
                    else:
                        glucose = round(random.uniform(4.5, 7.0), 1)
                    c.execute("""
                        INSERT INTO health_indicators
                          (id, user_id, indicator_type, "values", scene, note, recorded_at, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (
                        uid(), user_id, "BLOOD_GLUCOSE",
                        json.dumps({"value": glucose, "scene": "fasting"}),
                        "fasting", "空腹血糖",
                        days_ago(days), days_ago(days), days_ago(days)
                    ))
                    stats["indicators_created"] += 1

            # 体重数据
            for i in range(random.randint(2, 5)):
                days = random.randint(5, 85)
                hp_row = c.execute(
                    "SELECT weight_kg FROM health_profiles WHERE user_id=?", (user_id,)
                ).fetchone()
                base_weight = hp_row[0] if hp_row else 65
                weight_val = round(base_weight + random.uniform(-3, 3), 1)
                c.execute("""
                    INSERT INTO health_indicators
                      (id, user_id, indicator_type, "values", scene, note, recorded_at, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), user_id, "WEIGHT",
                    json.dumps({"value": weight_val}),
                    None, "体重记录",
                    days_ago(days), days_ago(days), days_ago(days)
                ))
                stats["indicators_created"] += 1

        # ── 2e. GuidanceRecord（调理方案）─────────────────────────────────
        existing_plans = c.execute(
            "SELECT COUNT(*) FROM guidance_records WHERE patient_id=? AND guidance_type='GUIDANCE'",
            (user_id,)
        ).fetchone()[0]

        if existing_plans == 0 and doctor_id:
            # 创建1个 PUBLISHED 方案
            plan_content = random.choice(PLAN_CONTENTS)
            if has_hypertension and has_diabetes:
                plan_content = PLAN_CONTENTS[1]  # 糖尿病方案
            elif has_hypertension:
                plan_content = PLAN_CONTENTS[0]  # 高血压方案
            elif atype == "ELDERLY":
                plan_content = PLAN_CONTENTS[4]  # 老年综合方案
            elif atype == "CHILD":
                plan_content = PLAN_CONTENTS[2]  # 气虚体质
            elif atype == "FEMALE":
                plan_content = PLAN_CONTENTS[2]

            created_days = random.randint(30, 120)
            c.execute("""
                INSERT INTO guidance_records
                  (id, patient_id, doctor_id, guidance_type, title, content, status, is_read,
                   created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                uid(), user_id, doctor_id, "GUIDANCE",
                f"个性化中医调理方案（{date_ago(created_days)}）",
                plan_content, "PUBLISHED", 1,
                days_ago(created_days), days_ago(created_days)
            ))
            stats["plans_created"] += 1

            # 50% 概率同时创建一个 DRAFT 草稿（新版本）
            if random.random() < 0.5:
                draft_content = random.choice(DRAFT_CONTENTS)
                c.execute("""
                    INSERT INTO guidance_records
                      (id, patient_id, doctor_id, guidance_type, title, content, status, is_read,
                       created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), user_id, doctor_id, "GUIDANCE",
                    f"调理方案草稿（{date_ago(7)}更新）",
                    draft_content, "DRAFT", 0,
                    days_ago(7), days_ago(7)
                ))
                stats["drafts_created"] += 1

        # ── 2f. AlertEvent（预警，仅高风险患者）──────────────────────────
        existing_alerts = c.execute(
            "SELECT COUNT(*) FROM alert_events WHERE user_id=?", (user_id,)
        ).fetchone()[0]

        if existing_alerts == 0 and rule_ids and (has_hypertension or has_diabetes):
            n_alerts = random.randint(1, 3)
            for i in range(n_alerts):
                severity = random.choice(["HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW"])
                disease = "HYPERTENSION" if has_hypertension else "DIABETES_T2"
                msg_templates = DISEASE_MESSAGES.get(disease, ["指标异常，请关注"])
                message = random.choice(msg_templates)
                if "{val}" in message:
                    if disease == "HYPERTENSION":
                        message = message.format(val=random.randint(145, 175))
                    else:
                        message = message.format(val=round(random.uniform(8.0, 13.0), 1))

                rule_id = random.choice(rule_ids)
                c.execute("""
                    INSERT INTO alert_events
                      (id, user_id, rule_id, indicator_id, severity, status,
                       trigger_value, message, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), user_id, rule_id, None, severity, "OPEN",
                    json.dumps({}),
                    message,
                    days_ago(random.randint(1, 30)),
                    days_ago(random.randint(0, 5))
                ))
                stats["alerts_created"] += 1

        # ── 2g. FollowupPlan（无随访计划的患者）─────────────────────────
        existing_plans_fw = c.execute(
            "SELECT COUNT(*) FROM followup_plans WHERE user_id=?", (user_id,)
        ).fetchone()[0]

        if existing_plans_fw == 0 and atype in ("ELDERLY", "KEY_FOCUS") and (has_hypertension or has_diabetes):
            disease_type = "HYPERTENSION" if has_hypertension else "DIABETES_T2"
            plan_id = uid()
            start = date_ago(random.randint(14, 60))
            end_dt = (date.today() + timedelta(weeks=12)).isoformat()

            c.execute("""
                INSERT INTO followup_plans
                  (id, user_id, disease_type, status, start_date, end_date, note,
                   created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                plan_id, user_id, disease_type, "ACTIVE",
                start, end_dt,
                f"慢病管理随访计划（{disease_type}）",
                now_str(), now_str()
            ))
            stats["followup_plans_created"] += 1

            # 创建随访任务（每7天一次）
            current = date.today() + timedelta(days=7)
            end_date_obj = date.today() + timedelta(weeks=12)
            while current <= end_date_obj:
                c.execute("""
                    INSERT INTO followup_tasks
                      (id, plan_id, task_type, name, scheduled_date, required, meta,
                       created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    uid(), plan_id, "INDICATOR_REPORT",
                    random.choice(["血压血糖上报", "指标上报", "服药依从性检查"]),
                    current.isoformat(), 1,
                    json.dumps({"source": "seed"}),
                    now_str(), now_str()
                ))
                stats["followup_tasks_created"] += 1
                current += timedelta(days=7)

    conn.commit()

    # ══════════════════════════════════════════════════════════════════════════
    # 3. 补充 GuidanceTemplate 模板
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[3] 补充指导方案模板...")

    for tpl in EXTRA_TEMPLATES:
        existing = c.execute(
            "SELECT id FROM guidance_templates WHERE name=?", (tpl["name"],)
        ).fetchone()
        if not existing:
            c.execute("""
                INSERT INTO guidance_templates
                  (id, name, guidance_type, scope, content, tags, is_active,
                   created_by, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                uid(), tpl["name"], tpl["guidance_type"],
                tpl.get("scope", "PERSONAL"),
                tpl["content"], tpl.get("tags", ""),
                1, admin_id or uid(),
                now_str(), now_str()
            ))
            stats["templates_created"] += 1

    conn.commit()

    # ══════════════════════════════════════════════════════════════════════════
    # 4. 最终统计
    # ══════════════════════════════════════════════════════════════════════════
    print("\n[4] 最终数据库统计...")
    tables = [
        "users", "patient_archives", "health_profiles", "constitution_assessments",
        "chronic_disease_records", "health_indicators", "guidance_records",
        "guidance_templates", "alert_events", "followup_plans", "followup_tasks"
    ]
    for t in tables:
        cnt = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"    {t}: {cnt}")

    conn.close()

    print("\n" + "="*55)
    print("补充完成！统计：")
    for k, v in stats.items():
        if v > 0:
            print(f"  {k}: {v}")
    print("="*55)


if __name__ == "__main__":
    run()
