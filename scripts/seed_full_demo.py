"""
全量演示数据补充脚本
覆盖：量表/咨询/宣教/干预/指导模板/患者标签/随访规则/定时任务/系统配置/版本/日志/字典等
运行：python scripts/seed_full_demo.py
"""
import asyncio, json, random, sys, uuid
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__file__)))

from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.archive import PatientArchive
from app.models.scale import Scale, ScaleQuestion, ScaleRecord
from app.models.consultation import Consultation, ConsultationMessage
from app.models.education import EducationRecord, EducationDelivery, EducationTemplate
from app.models.intervention import Intervention, InterventionRecord
from app.models.guidance import GuidanceTemplate, GuidanceRecord
from app.models.label import Label, LabelCategory, PatientLabel
from app.models.notification import Notification

UTC = timezone.utc

def now(offset_days=0):
    return datetime.now(UTC) - timedelta(days=offset_days)

def rand_date(start_days_ago=60, end_days_ago=1):
    d = random.randint(end_days_ago, start_days_ago)
    return now(d)

# ─────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────
async def get_users(db):
    r = await db.execute(select(User))
    users = r.scalars().all()
    doctors = [u for u in users if u.role.value == 'PROFESSIONAL']
    patients = [u for u in users if u.role.value == 'PATIENT']
    admin = next((u for u in users if u.role.value == 'ADMIN'), None)
    return doctors, patients, admin

async def get_archives(db):
    r = await db.execute(select(PatientArchive).where(PatientArchive.is_deleted == False))
    return r.scalars().all()

# ─────────────────────────────────────────────────────────
# 1. 量表
# ─────────────────────────────────────────────────────────
SCALES_DATA = [
    {
        "code": "PHQ9", "name": "PHQ-9 抑郁症筛查量表", "scale_type": "MENTAL_HEALTH",
        "description": "患者健康问卷抑郁量表，用于抑郁症的筛查与评估",
        "total_score": 27, "estimated_minutes": 5, "is_builtin": True,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":0,"max":4,"level":"正常","label":"无抑郁"},
            {"min":5,"max":9,"level":"轻度","label":"轻度抑郁"},
            {"min":10,"max":14,"level":"中度","label":"中度抑郁"},
            {"min":15,"max":19,"level":"偏重","label":"中重度抑郁"},
            {"min":20,"max":27,"level":"重度","label":"重度抑郁"}
        ]),
        "questions": [
            "做事时提不起劲或没有兴趣",
            "感到心情低落、沮丧或绝望",
            "入睡困难、睡不安稳或睡眠过多",
            "感觉疲倦或没有活力",
            "食欲不振或吃太多",
            "觉得自己很糟糕，或觉得自己很失败",
            "对事物专注有困难，如读报纸或看电视",
            "动作或说话速度缓慢，或坐立不安、烦躁",
            "有不如死掉或伤害自己的念头"
        ]
    },
    {
        "code": "GAD7", "name": "GAD-7 广泛性焦虑量表", "scale_type": "MENTAL_HEALTH",
        "description": "广泛性焦虑障碍7项量表，用于焦虑症的筛查",
        "total_score": 21, "estimated_minutes": 3, "is_builtin": True,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":0,"max":4,"level":"正常","label":"无焦虑"},
            {"min":5,"max":9,"level":"轻度","label":"轻度焦虑"},
            {"min":10,"max":14,"level":"中度","label":"中度焦虑"},
            {"min":15,"max":21,"level":"重度","label":"重度焦虑"}
        ]),
        "questions": [
            "感觉紧张、焦虑或烦躁",
            "不能停止或控制担忧",
            "对各种各样的事情担忧过多",
            "很难放松下来",
            "由于不安而无法静坐",
            "变得容易烦恼或急躁",
            "感到似乎将有可怕的事情发生而害怕"
        ]
    },
    {
        "code": "MMSE", "name": "MMSE 简易精神状态检查", "scale_type": "FUNCTION",
        "description": "简易精神状态检查量表，用于认知功能评估",
        "total_score": 30, "estimated_minutes": 10, "is_builtin": True,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":27,"max":30,"level":"正常","label":"认知正常"},
            {"min":21,"max":26,"level":"轻度","label":"轻度认知障碍"},
            {"min":10,"max":20,"level":"中度","label":"中度认知障碍"},
            {"min":0,"max":9,"level":"重度","label":"重度认知障碍"}
        ]),
        "questions": [
            "今年是哪一年？","现在是什么季节？","今天是几号？","今天是星期几？","现在是几月份？",
            "我们在哪个省市？","我们在哪个区县？","我们在哪个街道/乡镇？","这里是什么地方？","这里是第几层楼？",
            "复述：皮球","复述：国旗","复述：树木",
            "100减7等于多少？","再减7？","再减7？","再减7？","再减7？",
            "回忆：皮球","回忆：国旗","回忆：树木",
            "这是什么？（铅笔）","这是什么？（手表）",
            "请重复：大家齐心协力拉紧绳",
            "用右手拿纸，双手折叠，放在大腿上（三步骤）",
            "请照这个做（闭眼）",
            "请写一个完整的句子",
            "请照样画图（两个交叉五边形）"
        ]
    },
    {
        "code": "ADL", "name": "ADL 日常生活能力量表", "scale_type": "FUNCTION",
        "description": "日常生活活动能力评估，用于老年人功能状态评定",
        "total_score": 64, "estimated_minutes": 8, "is_builtin": True,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":14,"max":20,"level":"正常","label":"日常生活能力完好"},
            {"min":21,"max":40,"level":"轻度","label":"轻度功能受损"},
            {"min":41,"max":64,"level":"中重度","label":"中重度功能受损"}
        ]),
        "questions": [
            "上厕所","进食","穿衣","梳洗","行走","洗澡",
            "上下楼梯","做饭","做家务","使用交通工具",
            "购物","管理财务","服药","使用电话"
        ]
    },
    {
        "code": "MNA", "name": "MNA 营养状况评估", "scale_type": "DISEASE",
        "description": "微型营养评定量表，用于老年人营养状况评估",
        "total_score": 30, "estimated_minutes": 6, "is_builtin": False,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":24,"max":30,"level":"正常","label":"营养状况良好"},
            {"min":17,"max":23,"level":"风险","label":"营养不良风险"},
            {"min":0,"max":16,"level":"不良","label":"营养不良"}
        ]),
        "questions": [
            "过去3个月内是否因食欲下降、消化问题导致食物摄入减少？",
            "过去3个月内体重丢失情况",
            "活动能力",
            "过去3个月内是否有心理应激或急性疾病？",
            "神经精神问题",
            "体质指数BMI"
        ]
    },
    {
        "code": "FRAIL", "name": "FRAIL 衰弱综合征评估", "scale_type": "DISEASE",
        "description": "老年衰弱综合征筛查量表",
        "total_score": 5, "estimated_minutes": 3, "is_builtin": False,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":0,"max":0,"level":"健壮","label":"无衰弱"},
            {"min":1,"max":2,"level":"衰弱前期","label":"衰弱前期"},
            {"min":3,"max":5,"level":"衰弱","label":"衰弱综合征"}
        ]),
        "questions": [
            "疲乏感：您是否经常感到疲乏？",
            "耐力：您爬一层楼梯是否有困难？",
            "行动：您走完100米是否有困难？",
            "疾病：是否患有5种以上慢性病？",
            "体重减轻：1年内体重是否减轻超过5%？"
        ]
    },
    {
        "code": "AUDIT", "name": "AUDIT 饮酒问题筛查", "scale_type": "DISEASE",
        "description": "酒精使用障碍识别测试",
        "total_score": 40, "estimated_minutes": 5, "is_builtin": False,
        "scoring_rule": json.dumps({"method": "sum"}),
        "level_rules": json.dumps([
            {"min":0,"max":7,"level":"低风险","label":"低风险饮酒"},
            {"min":8,"max":15,"level":"危险","label":"危险性饮酒"},
            {"min":16,"max":19,"level":"有害","label":"有害性饮酒"},
            {"min":20,"max":40,"level":"依赖","label":"酒精依赖"}
        ]),
        "questions": [
            "您多久喝一次含酒精的饮料？",
            "平时喝酒，每次喝多少标准份？",
            "一次喝六份以上，多久发生一次？",
            "一旦开始喝酒，就停不下来，多久一次？",
            "因为喝酒，无法处理本应完成的事情，多久一次？",
            "喝酒后第二天早上，需要喝一杯来开始新的一天，多久一次？",
            "喝酒后感到愧疚或后悔，多久一次？",
            "因为喝酒，想不起前一天晚上发生的事，多久一次？",
            "您或别人因为您喝酒而受伤过吗？",
            "亲属/朋友/医生是否建议您减少喝酒？"
        ]
    },
    {
        "code": "TCM_BODY", "name": "中医体质综合评估量表", "scale_type": "CONSTITUTION",
        "description": "综合评估九种中医体质的专项量表",
        "total_score": 100, "estimated_minutes": 15, "is_builtin": False,
        "scoring_rule": json.dumps({"method": "weighted"}),
        "level_rules": json.dumps([
            {"min":0,"max":39,"level":"偏颇质","label":"偏颇体质"},
            {"min":40,"max":59,"level":"兼夹质","label":"兼夹体质"},
            {"min":60,"max":100,"level":"平和质","label":"平和体质"}
        ]),
        "questions": [
            "您精力充沛吗？","您容易疲乏吗？","您容易气短（呼吸短促、接不上气）吗？",
            "您嘴唇的颜色比一般人红吗？","您容易便秘或大便干燥吗？",
            "您脸部两颧潮红或偏红吗？","您感到身体发热，手脚发热吗？",
            "您手脚发凉吗？","您胃脘部、背部、腰膝部怕冷吗？",
            "您比一般人更怕冷、更容易感冒吗？"
        ]
    },
]

async def seed_scales(db):
    existing = (await db.execute(select(func.count()).select_from(Scale))).scalar_one()
    if existing >= len(SCALES_DATA):
        print(f"  量表已存在 {existing} 条，跳过")
        return

    for sd in SCALES_DATA:
        ex = (await db.execute(select(Scale).where(Scale.code == sd["code"]))).scalar_one_or_none()
        if ex:
            continue
        s = Scale(
            code=sd["code"], name=sd["name"], scale_type=sd["scale_type"],
            description=sd["description"], total_score=sd["total_score"],
            estimated_minutes=sd["estimated_minutes"], is_builtin=sd["is_builtin"],
            scoring_rule=sd["scoring_rule"], level_rules=sd["level_rules"],
        )
        db.add(s)
        await db.flush()
        opts_4 = json.dumps([{"text":"没有","score":0},{"text":"偶尔","score":1},{"text":"有时","score":2},{"text":"经常","score":3}])
        opts_4b= json.dumps([{"text":"完全正常","score":1},{"text":"轻度受损","score":2},{"text":"中度受损","score":3},{"text":"严重受损","score":4}])
        opts_yn= json.dumps([{"text":"是","score":1},{"text":"否","score":0}])
        for i, q in enumerate(sd["questions"], 1):
            opts = opts_4
            if sd["code"] == "ADL": opts = opts_4b
            if sd["code"] == "FRAIL": opts = opts_yn
            if sd["code"] == "MMSE": opts = json.dumps([{"text":"正确","score":1},{"text":"错误","score":0}])
            db.add(ScaleQuestion(
                scale_id=s.id, question_no=i, question_text=q,
                question_type="SINGLE", options=opts, is_required=True
            ))
    await db.flush()
    print(f"  量表: {len(SCALES_DATA)} 条插入完成")


async def seed_scale_records(db, archives):
    existing = (await db.execute(select(func.count()).select_from(ScaleRecord))).scalar_one()
    if existing >= 30:
        print(f"  量表记录已存在 {existing} 条，跳过")
        return

    scales_r = await db.execute(select(Scale))
    scales = scales_r.scalars().all()
    if not scales:
        print("  无量表，跳过量表记录")
        return

    level_map = {
        "PHQ9": [("正常",2.0),("轻度",7.0),("中度",12.0)],
        "GAD7": [("正常",3.0),("轻度",6.0),("中度",11.0)],
        "MMSE": [("正常",28.0),("轻度",24.0),("中度",18.0)],
        "ADL":  [("正常",16.0),("轻度",28.0),("中重度",45.0)],
        "MNA":  [("正常",26.0),("风险",20.0),("不良",14.0)],
        "FRAIL":[("健壮",0.0),("衰弱前期",1.0),("衰弱",3.0)],
        "AUDIT":[("低风险",4.0),("危险",10.0),("有害",17.0)],
        "TCM_BODY":[("平和质",65.0),("兼夹质",48.0),("偏颇质",30.0)],
    }
    conclusions = {
        "PHQ9": {"正常":"抑郁筛查阴性，无需特殊干预","轻度":"存在轻度抑郁倾向，建议关注情绪变化","中度":"中度抑郁，建议心理评估和干预"},
        "GAD7": {"正常":"焦虑筛查阴性","轻度":"轻度焦虑，建议放松训练","中度":"中度焦虑，需进一步评估"},
        "MMSE": {"正常":"认知功能正常","轻度":"轻度认知功能下降，建议定期复查","中度":"中度认知障碍，需专科评估"},
        "ADL":  {"正常":"日常生活能力完好","轻度":"轻度功能受损，建议康复指导","中重度":"日常生活能力明显受损"},
        "MNA":  {"正常":"营养状况良好","风险":"存在营养不良风险，建议营养干预","不良":"营养不良，需加强营养支持"},
        "FRAIL":{"健壮":"无衰弱表现","衰弱前期":"衰弱前期，建议运动干预","衰弱":"衰弱综合征，需综合干预"},
        "AUDIT":{"低风险":"饮酒风险低","危险":"危险性饮酒，建议减量","有害":"有害性饮酒，需医学干预"},
        "TCM_BODY":{"平和质":"体质平和，继续保持","兼夹质":"兼夹体质，需针对性调护","偏颇质":"偏颇体质，需积极干预"},
    }
    count = 0
    for arch in random.sample(archives, min(len(archives), 20)):
        for scale in random.sample(scales, min(len(scales), random.randint(2, 4))):
            lvl_list = level_map.get(scale.code, [("正常", 15.0)])
            lvl, score = random.choice(lvl_list)
            score += random.uniform(-1, 1)
            conc = conclusions.get(scale.code, {}).get(lvl, "评估完成，请结合临床综合判断。")
            rec = ScaleRecord(
                scale_id=scale.id,
                patient_archive_id=str(arch.id),
                answers=json.dumps({f"q{i}": random.randint(0, 3) for i in range(1, 10)}),
                total_score=round(score, 1),
                level=lvl,
                conclusion=conc,
                completed_at=rand_date(90, 1),
            )
            db.add(rec)
            count += 1
    await db.flush()
    print(f"  量表记录: {count} 条插入完成")


# ─────────────────────────────────────────────────────────
# 2. 咨询
# ─────────────────────────────────────────────────────────
CONSULT_TOPICS = [
    ("血压控制效果咨询", "最近血压控制不稳定，需要调整用药方案吗？"),
    ("血糖偏高怎么处理", "最近空腹血糖7.8，餐后血糖11.2，需要来复诊吗？"),
    ("中药调理体质建议", "体质评估结果显示气虚质，有哪些中药可以调理？"),
    ("运动方案咨询", "心脏不好，想了解适合的运动类型和强度"),
    ("饮食禁忌咨询", "高血压患者哪些食物要少吃？"),
    ("头痛头晕是否正常", "最近早上起床经常头晕，血压也偏高，需要注意吗？"),
    ("腰膝酸软中医调理", "最近腰膝酸软，走路乏力，有什么中医调理方法？"),
    ("失眠改善方法", "最近睡眠质量很差，经常凌晨2-3点醒来，有什么好方法？"),
    ("复诊时间安排", "距上次随访已经两个月，想预约下次门诊时间"),
    ("体检报告解读", "体检报告显示血脂偏高，需要服药吗还是饮食控制即可？"),
]

DOCTOR_REPLIES = [
    "您好，根据您的情况，建议{action}。如有不适请及时就诊。",
    "感谢您的信任。从您描述的症状来看，{action}，请按时服药并定期监测。",
    "您的问题很常见。建议{action}，同时注意休息，保持良好作息。",
    "根据您的体质和病史，{action}。我们下次随访时可以详细讨论。",
]

ACTIONS = [
    "继续当前用药方案，每日监测血压",
    "适当调整饮食结构，减少盐分摄入",
    "增加有氧运动，每天步行30分钟",
    "来院复查血糖和相关指标",
    "口服中药颗粒调理，配合穴位按摩",
    "保持心情舒畅，避免情绪波动",
    "注意保暖，减少过度劳累",
    "建议转介心理科评估",
]

async def seed_consultations(db, archives, doctors):
    existing = (await db.execute(select(func.count()).select_from(Consultation))).scalar_one()
    if existing >= 20:
        print(f"  咨询已存在 {existing} 条，跳过")
        return

    doctor = doctors[0] if doctors else None
    statuses = ["OPEN", "REPLIED", "CLOSED"]
    count = 0
    for arch in random.sample(archives, min(len(archives), 18)):
        topic, patient_q = random.choice(CONSULT_TOPICS)
        status = random.choice(statuses)
        created = rand_date(60, 2)
        c = Consultation(
            archive_id=arch.id,
            doctor_id=doctor.id if doctor else None,
            title=topic,
            status=status,
            priority=random.choice(["NORMAL", "NORMAL", "URGENT"]),
            created_at=created,
            updated_at=created,
        )
        db.add(c)
        await db.flush()
        # 患者提问
        db.add(ConsultationMessage(
            consultation_id=c.id,
            sender_id=arch.id,
            sender_type="PATIENT",
            content=patient_q,
            msg_type="TEXT",
            created_at=created,
        ))
        # 医生回复
        if status in ("REPLIED", "CLOSED") and doctor:
            action = random.choice(ACTIONS)
            reply = random.choice(DOCTOR_REPLIES).format(action=action)
            db.add(ConsultationMessage(
                consultation_id=c.id,
                sender_id=doctor.id,
                sender_type="DOCTOR",
                content=reply,
                msg_type="TEXT",
                created_at=created + timedelta(hours=random.randint(1, 12)),
            ))
            if status == "CLOSED":
                c.closed_at = created + timedelta(days=random.randint(1, 3))
        count += 1
    await db.flush()
    print(f"  咨询: {count} 条插入完成")


# ─────────────────────────────────────────────────────────
# 3. 宣教模板 + 宣教记录
# ─────────────────────────────────────────────────────────
EDU_TEMPLATES = [
    ("高血压患者饮食指导", "DISEASE", "PUBLIC",
     "1. 低盐饮食：每日食盐摄入不超过6g\n2. 多吃蔬菜水果，每日500g以上\n3. 减少动物脂肪摄入\n4. 戒烟限酒\n5. 保持体重在正常范围内"),
    ("糖尿病饮食管理", "DISEASE", "PUBLIC",
     "1. 控制总热量摄入，按标准体重计算\n2. 选择低升糖指数食物\n3. 定时定量进餐，少食多餐\n4. 增加膳食纤维摄入\n5. 严格控制单糖摄入"),
    ("气虚体质调护方案", "CONSTITUTION", "PUBLIC",
     "气虚体质特征：容易疲乏、气短懒言、自汗\n\n调护原则：\n1. 饮食：多吃益气食物，如山药、红枣、黄芪煮粥\n2. 运动：选择和缓运动，太极拳、八段锦\n3. 起居：避免过度劳累，保证充足睡眠\n4. 情志：保持积极乐观，避免过思过虑"),
    ("冬季养生保健知识", "SEASONAL", "PUBLIC",
     "冬季养生要点：\n1. 早卧晚起，保证8小时睡眠\n2. 注意保暖，重点保护头颈腰腹\n3. 适度运动，避免在严寒中剧烈运动\n4. 饮食温补：羊肉、核桃、黑芝麻\n5. 冬病夏治的对立面：冬季注重藏精"),
    ("血压自我监测方法", "DISEASE", "DEPT",
     "正确测量血压：\n1. 测量前静坐5分钟\n2. 不要在吸烟、饮酒、喝咖啡后立即测量\n3. 选择固定时间（早晨起床后、晚睡前）\n4. 连续测量2次取平均值\n5. 记录测量结果，方便复诊参考"),
    ("慢性病患者运动指南", "EXERCISE", "DEPT",
     "慢性病患者运动原则：\n1. 从低强度开始，循序渐进\n2. 每周至少150分钟中等强度有氧运动\n3. 推荐：步行、游泳、太极拳、广场舞\n4. 运动时携带急救药物\n5. 出现心悸、气促立即停止"),
    ("用药安全教育", "MEDICATION", "PUBLIC",
     "安全用药须知：\n1. 按时按量服药，不可自行停药\n2. 了解所服药物的常见副作用\n3. 多种药物同服需咨询医生\n4. 妥善保存药品，注意有效期\n5. 出现不良反应立即就医"),
    ("阳虚体质冬季调护", "CONSTITUTION", "PERSONAL",
     "阳虚体质冬季养护：\n1. 艾灸：关元、气海、命门穴，每次15-20分钟\n2. 饮食：当归生姜羊肉汤，核桃仁炒韭菜\n3. 运动：避免清晨户外运动，选择午后阳光充足时\n4. 足浴：每晚温水泡脚加生姜，促进阳气运行"),
    ("痰湿体质减重方案", "CONSTITUTION", "PERSONAL",
     "痰湿体质减重要点：\n1. 饮食：薏苡仁、赤小豆、冬瓜利湿消肿\n2. 运动：坚持有氧运动，每次30分钟以上\n3. 按摩：丰隆穴、足三里穴，化痰健脾\n4. 环境：保持生活环境干燥通风\n5. 避免贪凉饮冷，少食肥甘厚味"),
    ("中风预防知识", "DISEASE", "PUBLIC",
     "脑卒中预防ABC法则：\n A-Antiplatelet（抗血小板）\n B-Blood pressure（控血压）\n C-Cholesterol（降血脂）\n\n生活预防：\n1. 控制血压、血糖、血脂\n2. 戒烟限酒\n3. 规律运动\n4. 识别FAST症状（面瘫、臂软、言语不清、快速拨打120）"),
]

async def seed_education(db, archives, doctors):
    existing = (await db.execute(select(func.count()).select_from(EducationTemplate))).scalar_one()
    if existing >= len(EDU_TEMPLATES):
        print(f"  宣教模板已存在 {existing} 条，跳过")
    else:
        doctor = doctors[0] if doctors else None
        for name, edu_type, scope, content in EDU_TEMPLATES:
            db.add(EducationTemplate(
                name=name, edu_type=edu_type, scope=scope,
                content=content, used_count=random.randint(0, 20),
                created_by=doctor.id if doctor else None,
            ))
        await db.flush()
        print(f"  宣教模板: {len(EDU_TEMPLATES)} 条插入完成")

    existing_r = (await db.execute(select(func.count()).select_from(EducationRecord))).scalar_one()
    if existing_r >= 20:
        print(f"  宣教记录已存在 {existing_r} 条，跳过")
        return

    doctor = doctors[0] if doctors else None
    count = 0
    for i, (name, edu_type, scope, content) in enumerate(EDU_TEMPLATES[:8]):
        batch_size = random.randint(3, 8)
        batch_archives = random.sample(archives, min(len(archives), batch_size))
        sent_at = rand_date(60, 1)
        rec = EducationRecord(
            title=name, edu_type=edu_type,
            content=content,
            send_scope="BATCH" if len(batch_archives) > 1 else "SINGLE",
            send_methods='["APP","STATION"]',
            sent_at=sent_at, scheduled_at=sent_at,
            created_by=doctor.id if doctor else None,
            created_at=sent_at,
        )
        db.add(rec)
        await db.flush()
        for arch in batch_archives:
            read = random.random() > 0.4
            db.add(EducationDelivery(
                record_id=rec.id,
                patient_id=arch.id,
                send_method=random.choice(["APP", "STATION"]),
                read_status="READ" if read else "UNREAD",
                read_at=(sent_at + timedelta(hours=random.randint(1, 48))) if read else None,
                delivered_at=sent_at,
            ))
        count += 1
    await db.flush()
    print(f"  宣教记录: {count} 条插入完成")


# ─────────────────────────────────────────────────────────
# 4. 干预方案 + 执行记录
# ─────────────────────────────────────────────────────────
INTERVENTIONS_DATA = [
    ("高血压综合干预方案", "COMBINED", "BALANCED", "将血压控制在130/80mmHg以下，减少并发症风险",
     "针刺曲池、足三里、太冲穴；配合耳穴压豆降压沟；同时给予食疗方案：芹菜汁每日饮用"),
    ("气虚体质针灸调理", "ACUPUNCTURE", "QI_DEFICIENCY", "补气固表，增强体质",
     "取穴：足三里、气海、关元、脾俞、胃俞；手法：补法；每次留针30分钟"),
    ("痰湿体质推拿治疗", "MASSAGE", "PHLEGM_DAMPNESS", "健脾化湿，消痰减重",
     "推拿手法：摩腹、揉天枢、按丰隆；每次45分钟；重点刺激脾经和胃经循行路线"),
    ("糖尿病中药调理", "HERBAL", "YIN_DEFICIENCY", "滋阴清热，改善血糖代谢",
     "处方：黄芪30g、山药20g、葛根15g、苍术10g、玄参15g；水煎服，每日1剂，分两次"),
    ("老年骨质疏松食疗方案", "DIET", "YANG_DEFICIENCY", "补肾壮骨，预防骨折",
     "每日食疗方案：早餐加黑芝麻糊；午餐骨头汤；晚餐核桃仁；补充维生素D；避免浓茶咖啡"),
    ("失眠中医综合干预", "COMBINED", "YIN_DEFICIENCY", "改善睡眠质量，恢复精力",
     "1. 中药：酸枣仁汤加减\n2. 针灸：神门、安眠穴\n3. 耳针：心、神门、皮质下\n4. 足浴：磁石、夜交藤"),
    ("慢性疲劳中医干预", "ACUPUNCTURE", "QI_DEFICIENCY", "振奋阳气，恢复精力",
     "主穴：百会、气海、关元、足三里；配穴：脾俞、肾俞；每周2次，疗程8周"),
    ("高脂血症食疗干预", "DIET", "PHLEGM_DAMPNESS", "化痰降脂，改善血脂代谢",
     "1. 山楂荷叶茶：每日代茶饮\n2. 薏苡仁粥：每周3次\n3. 减少动物脂肪，增加深海鱼\n4. 适量运动"),
]

async def seed_interventions(db, archives, doctors):
    existing = (await db.execute(select(func.count()).select_from(Intervention))).scalar_one()
    if existing >= 20:
        print(f"  干预方案已存在 {existing} 条，跳过")
        return

    doctor = doctors[0] if doctors else None
    count = 0
    for arch in random.sample(archives, min(len(archives), 20)):
        n = random.randint(1, 2)
        for plan_name, itype, constitution, goal, detail in random.sample(INTERVENTIONS_DATA, n):
            start = (date.today() - timedelta(days=random.randint(10, 90)))
            weeks = random.choice([4, 6, 8])
            status = random.choice(["IN_PROGRESS", "IN_PROGRESS", "COMPLETED", "PAUSED"])
            inv = Intervention(
                patient_id=arch.id,
                plan_name=plan_name, intervention_type=itype,
                target_constitution=constitution, goal=goal,
                content_detail=detail,
                precaution="注意观察不良反应，如有不适请及时告知",
                executor_id=doctor.id if doctor else None,
                start_date=start, duration_weeks=weeks,
                frequency=random.choice(["DAILY", "WEEKLY", "BIWEEKLY"]),
                status=status,
                created_by=doctor.id if doctor else None,
            )
            db.add(inv)
            await db.flush()
            # 执行记录
            sessions = random.randint(2, 6)
            effects = ["EFFECTIVE", "EFFECTIVE", "PARTIAL", "NOT_ASSESSED"]
            feedbacks = ["感觉好多了", "症状有所改善", "效果不明显", "还需继续治疗", "很好，坚持治疗"]
            for s in range(1, sessions + 1):
                db.add(InterventionRecord(
                    intervention_id=inv.id,
                    session_no=s,
                    executed_at=datetime.combine(
                        start + timedelta(weeks=s-1), datetime.min.time()
                    ).replace(tzinfo=UTC),
                    effectiveness=random.choice(effects),
                    patient_feedback=random.choice(feedbacks),
                    notes=f"第{s}次执行，患者配合度良好",
                    recorded_by=doctor.id if doctor else None,
                ))
            count += 1
    await db.flush()
    print(f"  干预方案: {count} 条（含执行记录）插入完成")


# ─────────────────────────────────────────────────────────
# 5. 指导模板
# ─────────────────────────────────────────────────────────
GUIDANCE_TEMPLATES_DATA = [
    ("高血压生活方式指导", "GUIDANCE", "PUBLIC",
     "血压管理生活方式要点：\n1. 限盐：每日<6g\n2. 减重：BMI控制在18.5-23.9\n3. 戒烟\n4. 限酒：男性<25g/日\n5. 有氧运动：每周150分钟\n6. 保持心情愉快"),
    ("糖尿病患者用药指导", "GUIDANCE", "PUBLIC",
     "口服降糖药使用注意事项：\n1. 按时按量服用，不可随意停药\n2. 二甲双胍随餐或餐后服用\n3. 出现低血糖（头晕、出汗、心慌）立即进食\n4. 定期监测血糖并记录"),
    ("气虚体质中医指导", "GUIDANCE", "PUBLIC",
     "气虚体质调护方案：\n饮食：黄芪、党参、白术炖鸡\n运动：轻柔的太极拳、八段锦\n穴位按摩：足三里、气海\n避免：过度劳累、大汗"),
    ("冠心病二级预防指导", "GUIDANCE", "DEPT",
     "冠心病患者注意事项：\n1. 坚持抗血小板、他汀类药物\n2. 控制危险因素：血压<130/80，血脂LDL<1.8\n3. 戒烟，避免二手烟\n4. 心脏康复运动训练\n5. 识别心绞痛发作及急救措施"),
    ("老年人防跌倒指导", "GUIDANCE", "DEPT",
     "防跌倒六大措施：\n1. 家居改造：浴室安装扶手、防滑垫\n2. 适当运动：平衡训练、下肢肌力训练\n3. 用药注意：避免引起头晕的药物\n4. 视力检查：定期验光配镜\n5. 穿合适鞋子\n6. 光线充足"),
    ("阳虚体质干预方案", "INTERVENTION", "PUBLIC",
     "阳虚体质综合干预：\n药物：金匮肾气丸\n饮食：当归生姜羊肉汤，韭菜炒核桃\n艾灸：命门、关元（每日15分钟）\n运动：避免清晨运动，选午后阳光时段\n起居：早睡，腰腹保暖"),
    ("颈椎病针灸干预", "INTERVENTION", "DEPT",
     "颈椎病针灸治疗方案：\n主穴：风池、颈百劳、大椎、后溪\n配穴：随症加减\n手法：平补平泻\n疗程：每周3次，4周为一疗程\n注意：急性期避免剧烈活动"),
    ("健康体检宣教", "EDUCATION", "PUBLIC",
     "定期健康体检提醒：\n1. 40岁以上每年体检一次\n2. 慢性病患者每6个月体检\n3. 重点项目：血压、血糖、血脂、心电图\n4. 女性加查：宫颈癌筛查、乳腺检查\n5. 男性加查：前列腺特异抗原（50岁以上）"),
    ("中医养生宣教", "EDUCATION", "PUBLIC",
     "中医四季养生要点：\n春：疏肝理气，多食青色蔬菜\n夏：清热养心，避暑防湿\n秋：润肺养阴，适时进补\n冬：补肾藏精，温阳御寒\n\n日常养生：早睡早起，饮食有节，劳逸结合"),
]

async def seed_guidance_templates(db, archives, doctors):
    existing = (await db.execute(select(func.count()).select_from(GuidanceTemplate))).scalar_one()
    if existing >= len(GUIDANCE_TEMPLATES_DATA):
        print(f"  指导模板已存在 {existing} 条，跳过")
        return

    doctor = doctors[0] if doctors else None
    from app.models.enums import GuidanceType, TemplateScope
    type_map = {"GUIDANCE": GuidanceType.GUIDANCE, "INTERVENTION": GuidanceType.INTERVENTION, "EDUCATION": GuidanceType.EDUCATION}
    scope_map = {"PUBLIC": TemplateScope.PUBLIC, "DEPT": TemplateScope.DEPARTMENT, "PERSONAL": TemplateScope.PERSONAL}
    for name, gtype, scope, content in GUIDANCE_TEMPLATES_DATA:
        db.add(GuidanceTemplate(
            name=name,
            guidance_type=type_map.get(gtype, GuidanceType.GUIDANCE),
            scope=scope_map.get(scope, TemplateScope.PUBLIC),
            content=content, tags=f"{gtype},慢病管理",
            is_active=True,
            created_by=doctor.id if doctor else None,
        ))
    await db.flush()
    print(f"  指导模板: {len(GUIDANCE_TEMPLATES_DATA)} 条插入完成")


# ─────────────────────────────────────────────────────────
# 6. 患者标签
# ─────────────────────────────────────────────────────────
async def seed_patient_labels(db, archives):
    existing = (await db.execute(select(func.count()).select_from(PatientLabel))).scalar_one()
    if existing >= 30:
        print(f"  患者标签已存在 {existing} 条，跳过")
        return

    labels_r = await db.execute(select(Label))
    labels = labels_r.scalars().all()
    if not labels:
        print("  无标签定义，跳过患者标签")
        return

    count = 0
    for arch in random.sample(archives, min(len(archives), 25)):
        existing_arch = (await db.execute(
            select(func.count()).select_from(PatientLabel).where(PatientLabel.patient_id == arch.id)
        )).scalar_one()
        if existing_arch > 0:
            continue
        n = random.randint(1, 3)
        for label in random.sample(labels, min(len(labels), n)):
            db.add(PatientLabel(
                patient_id=arch.id,
                label_id=label.id,
                created_at=rand_date(120, 7),
            ))
            count += 1
    await db.flush()
    print(f"  患者标签: {count} 条插入完成")


# ─────────────────────────────────────────────────────────
# 7. 系统配置 / 版本 / 字典 / 定时任务
# ─────────────────────────────────────────────────────────
async def seed_system_data(db):
    sql = __import__('sqlalchemy').text

    # system_configs  (columns: id, key, value, description, group, is_public)
    r = await db.execute(sql("SELECT COUNT(*) FROM system_configs"))
    if r.scalar() == 0:
        configs = [
            ("system", "platform_name", "中医慢病与治未病管理平台", "平台名称"),
            ("system", "platform_version", "V2.1.0", "平台版本"),
            ("system", "max_patients_per_doctor", "200", "每位医生最大管辖患者数"),
            ("system", "alert_notify_delay_minutes", "30", "预警通知延迟（分钟）"),
            ("system", "session_timeout_minutes", "120", "会话超时时间"),
            ("followup", "default_plan_days", "30", "默认随访计划天数"),
            ("followup", "reminder_before_days", "1", "随访提前提醒天数"),
            ("assessment", "auto_score_enabled", "true", "是否自动评分"),
            ("assessment", "report_auto_generate", "true", "评分后是否自动生成报告"),
            ("notification", "sms_enabled", "false", "是否启用短信通知"),
            ("notification", "push_enabled", "true", "是否启用推送通知"),
            ("security", "password_min_length", "8", "密码最小长度"),
            ("security", "login_fail_max_times", "5", "登录失败最大次数"),
        ]
        for grp, key, val, desc in configs:
            await db.execute(sql(
                "INSERT INTO system_configs (id, `group`, `key`, `value`, description, is_public) VALUES (:id,:g,:k,:v,:d,1)"
            ), {"id": str(uuid.uuid4()), "g": grp, "k": key, "v": val, "d": desc})
        print(f"  系统配置: {len(configs)} 条插入完成")

    # system_versions  (columns: id, version_no, release_notes, is_current, released_by, released_at)
    r = await db.execute(sql("SELECT COUNT(*) FROM system_versions"))
    if r.scalar() == 0:
        versions = [
            ("V1.0.0", "初始版本发布：基础档案管理、体质评估", "2025-01-15 00:00:00", False),
            ("V1.1.0", "新增随访管理模块，支持高血压/糖尿病随访计划", "2025-03-20 00:00:00", False),
            ("V1.2.0", "新增中医干预/宣教模块，量表评估库扩充", "2025-06-10 00:00:00", False),
            ("V2.0.0", "全面重构前端，新增管理中心，支持多机构", "2025-09-01 00:00:00", False),
            ("V2.1.0", "新增AI辅助评估，危急值预警升级，统计分析增强", "2026-01-08 00:00:00", True),
        ]
        for ver, notes, released_at, is_current in versions:
            await db.execute(sql(
                "INSERT INTO system_versions (id, version_no, release_notes, is_current, released_at) VALUES (:id,:v,:n,:c,:r)"
            ), {"id": str(uuid.uuid4()), "v": ver, "n": notes, "c": is_current, "r": released_at})
        print(f"  系统版本: {len(versions)} 条插入完成")

    # dict_groups / dict_items  (dict_groups columns: id, code, name, description, sort_order, is_active)
    r = await db.execute(sql("SELECT COUNT(*) FROM dict_items"))
    if r.scalar() < 20:
        g_r = await db.execute(sql("SELECT id, code FROM dict_groups"))
        groups = {row[1]: row[0] for row in g_r.fetchall()}
        if "DISEASE_TYPE" not in groups:
            for gc, gn, gd, gs in [("DISEASE_TYPE","疾病类型","慢病类型字典",1),("BODY_PART","身体部位","检查部位字典",2)]:
                await db.execute(sql(
                    "INSERT INTO dict_groups (id, code, name, description, sort_order, is_active) VALUES (:id,:c,:n,:d,:s,1)"
                ), {"id": str(uuid.uuid4()), "c": gc, "n": gn, "d": gd, "s": gs})
            g_r2 = await db.execute(sql("SELECT id, code FROM dict_groups"))
            groups = {row[1]: row[0] for row in g_r2.fetchall()}
        disease_gid = groups.get("DISEASE_TYPE")
        if disease_gid:
            items = [
                ("HYPERTENSION","高血压",1), ("DIABETES_T2","2型糖尿病",2),
                ("CORONARY","冠心病",3), ("STROKE","脑卒中",4),
                ("COPD","慢阻肺",5), ("CKD","慢性肾病",6),
                ("OSTEOPOROSIS","骨质疏松",7), ("HYPERLIPIDEMIA","高脂血症",8),
                ("FATTY_LIVER","脂肪肝",9), ("GOUT","痛风",10),
            ]
            for code, name, seq in items:
                await db.execute(sql(
                    "INSERT OR IGNORE INTO dict_items (id, group_id, item_code, item_name, sort_order, status) VALUES (:id,:g,:c,:n,:s,'ACTIVE')"
                ), {"id": str(uuid.uuid4()), "g": disease_gid, "c": code, "n": name, "s": seq})
        print("  字典数据: 疾病类型插入完成")

    # scheduled_tasks  (columns: id, name, task_key, description, cron_expr, status, params, last_run_at, next_run_at, last_result)
    r = await db.execute(sql("SELECT COUNT(*) FROM scheduled_tasks"))
    if r.scalar() == 0:
        tasks = [
            ("HIS患者数据同步", "sync_his_patients", "0 2 * * *", "ACTIVE", "2026-03-03 02:00:00", "SUCCESS"),
            ("LIS检验报告同步", "sync_lis_reports", "0 */4 * * *", "ACTIVE", "2026-03-04 00:00:00", "SUCCESS"),
            ("预警规则定时检测", "alert_check", "*/30 * * * *", "ACTIVE", "2026-03-04 14:30:00", "SUCCESS"),
            ("随访到期提醒", "followup_reminder", "0 8 * * *", "ACTIVE", "2026-03-04 08:00:00", "SUCCESS"),
            ("清理过期会话", "clean_expired_sessions", "0 3 * * *", "ACTIVE", "2026-03-04 03:00:00", "SUCCESS"),
            ("月度统计报表生成", "generate_monthly_report", "0 1 1 * *", "ACTIVE", "2026-03-01 01:00:00", "SUCCESS"),
            ("数据库备份", "backup_database", "0 4 * * 0", "ACTIVE", "2026-03-02 04:00:00", "SUCCESS"),
            ("设备报告采集同步", "sync_device_reports", "0 6 * * *", "DISABLED", None, None),
        ]
        for name, key, cron, status, last_run, last_result in tasks:
            await db.execute(sql(
                "INSERT INTO scheduled_tasks (id, name, task_key, description, cron_expr, status, last_run_at, last_result, run_count) VALUES (:id,:n,:k,:d,:e,:s,:lr,:lres,0)"
            ), {"id": str(uuid.uuid4()), "n": name, "k": key, "d": name, "e": cron, "s": status,
                "lr": last_run, "lres": last_result})
        print(f"  定时任务: {len(tasks)} 条插入完成")

    # login_logs  (columns: id, user_id, username, ip_address, user_agent, status, fail_reason)
    r = await db.execute(sql("SELECT COUNT(*) FROM login_logs"))
    if r.scalar() < 30:
        users_r = await db.execute(sql("SELECT id, phone FROM users LIMIT 10"))
        users_list = users_r.fetchall()
        ips = ["192.168.1.100", "192.168.1.101", "10.0.0.5", "172.16.0.20", "192.168.0.88"]
        agents = ["Chrome/Windows", "Safari/iPhone", "Chrome/MacOS", "Edge/Windows", "Firefox/Linux"]
        for _ in range(50):
            u = random.choice(users_list)
            dt = rand_date(30, 0)
            success = random.random() > 0.1
            await db.execute(sql(
                "INSERT INTO login_logs (id, user_id, ip_address, user_agent, status, fail_reason) VALUES (:id,:uid,:ip,:ua,:s,:fr)"
            ), {"id": str(uuid.uuid4()), "uid": u[0], "ip": random.choice(ips), "ua": random.choice(agents),
                "s": "SUCCESS" if success else "FAILED",
                "fr": None if success else "密码错误"})
        print("  登录日志: 50 条插入完成")

    # sms_logs  (columns: id, phone, content, sms_type, status, provider_msg_id, error_msg, retry_count)
    r = await db.execute(sql("SELECT COUNT(*) FROM sms_logs"))
    if r.scalar() == 0:
        users_r = await db.execute(sql("SELECT phone FROM users WHERE role='PATIENT' LIMIT 10"))
        phones = [row[0] for row in users_r.fetchall()]
        msg_types = [
            ("FOLLOWUP_REMINDER", "【治未病平台】您有一条随访任务待完成，请及时处理。"),
            ("ALERT_NOTIFY", "【治未病平台】健康预警：您的血压指标异常，请及时就医或联系您的健康管理师。"),
            ("APPT_REMINDER", "【治未病平台】您明日14:00有复诊预约，请准时到诊。"),
        ]
        for _ in range(20):
            phone = random.choice(phones) if phones else "13800000001"
            mtype, content = random.choice(msg_types)
            await db.execute(sql(
                "INSERT INTO sms_logs (id, phone, content, sms_type, status, retry_count) VALUES (:id,:p,:c,:t,:s,0)"
            ), {"id": str(uuid.uuid4()), "p": phone, "c": content, "t": mtype,
                "s": random.choice(["SUCCESS","SUCCESS","SUCCESS","FAILED"])})
        print("  短信日志: 20 条插入完成")

    await db.commit()


# ─────────────────────────────────────────────────────────
# 8. 通知补充
# ─────────────────────────────────────────────────────────
async def seed_notifications(db, archives, doctors):
    existing = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    if existing >= 30:
        print(f"  通知已存在 {existing} 条，跳过")
        return

    doctor = doctors[0] if doctors else None
    notif_data = [
        ("ALERT", "高血压预警通知", "您的血压指标超过安全阈值，请立即联系您的健康管理师"),
        ("FOLLOWUP", "随访任务提醒", "您有一条随访任务即将到期，请完成今日打卡"),
        ("PLAN_ISSUED", "健康方案已下达", "您的个性化健康管理方案已更新，请查看"),
        ("SYSTEM", "平台通知", "系统将于2026-03-10 02:00-04:00进行例行维护，请提前知悉"),
        ("EDUCATION", "健康宣教推送", "您有新的健康知识文章，点击查看"),
    ]
    count = 0
    for arch in random.sample(archives, min(len(archives), 20)):
        for ntype, title, content in random.sample(notif_data, random.randint(2, 3)):
            read = random.random() > 0.5
            db.add(Notification(
                archive_id=arch.id,
                sender_id=doctor.id if doctor else None,
                notif_type=ntype,
                title=title,
                content=content,
                status="READ" if read else "UNREAD",
                read_at=rand_date(5, 0) if read else None,
                created_at=rand_date(30, 1),
            ))
            count += 1
    await db.flush()
    print(f"  通知: {count} 条插入完成")


# ─────────────────────────────────────────────────────────
# 9. 随访规则 / 内容库补充
# ─────────────────────────────────────────────────────────
async def seed_followup_rules(db):
    r = await db.execute(__import__('sqlalchemy').text("SELECT COUNT(*) FROM followup_rules"))
    if r.scalar() >= 5:
        print("  随访规则已存在，跳过")
        return
    # followup_rules columns: id(INTEGER), name, trigger, frequency, method, archive_type_filter, description, is_active
    rules = [
        ("高血压标准随访规则", "SCHEDULED", "MONTHLY", "APP", "HYPERTENSION", "高血压患者每月随访"),
        ("糖尿病标准随访规则", "SCHEDULED", "MONTHLY", "APP", "DIABETES_T2", "糖尿病患者每月随访"),
        ("冠心病随访规则", "SCHEDULED", "BIMONTHLY", "PHONE", "CORONARY", "冠心病患者双月随访"),
        ("脑卒中康复随访规则", "SCHEDULED", "WEEKLY", "APP", "STROKE", "脑卒中患者每周随访"),
        ("通用慢病随访规则", "SCHEDULED", "MONTHLY", "APP", None, "通用慢病管理随访"),
    ]
    for name, trigger, freq, method, atype, desc in rules:
        await db.execute(__import__('sqlalchemy').text(
            "INSERT OR IGNORE INTO followup_rules (name, trigger, frequency, method, archive_type_filter, description, is_active) VALUES (:n,:t,:f,:m,:a,:d,1)"
        ), {"n": name, "t": trigger, "f": freq, "m": method, "a": atype, "d": desc})
    await db.commit()
    print(f"  随访规则: {len(rules)} 条插入完成")


async def seed_content(db, admin_id):
    from app.models.content import ContentItem
    from app.models.enums import ContentStatus
    existing = (await db.execute(select(func.count()).select_from(ContentItem))).scalar_one()
    if existing >= 15:
        print(f"  内容库已存在 {existing} 条，跳过")
        return
    articles = [
        ("高血压患者如何正确测量血压？", ["高血压"],
         "正确测量血压是控制高血压的第一步。测量前应静坐5分钟，避免运动、吸烟、饮酒后立即测量。应选择固定时间，早晨起床后和睡前各测一次，连测2次取平均值。"),
        ("气虚体质的饮食调养", ["中医体质"],
         "气虚体质者常感乏力、气短、容易感冒。饮食上宜选择健脾益气的食物，如山药、莲子、红枣、黄芪炖鸡等。避免生冷、辛辣、油腻食物。"),
        ("糖尿病血糖监测指南", ["糖尿病"],
         "糖尿病患者需要定期监测血糖。空腹血糖控制目标为4.4-7.0mmol/L，餐后2小时血糖<10.0mmol/L。出现低血糖（血糖<3.9mmol/L）时应立即进食15-20g碳水化合物。"),
        ("冬季养生：中医教你如何护阳", ["节气养生"],
         "冬季是藏精的季节，中医认为应早睡晚起，保护阳气。艾灸关元、气海穴可温补阳气，适量进补羊肉、核桃等温性食物，避免大量出汗消耗阳气。"),
        ("太极拳入门：适合慢性病患者的运动", ["运动养生"],
         "太极拳动作柔和缓慢，适合各年龄段慢性病患者练习。每次练习20-30分钟，每周3-5次。研究证明，规律练习太极拳可有效降低血压、改善血糖控制。"),
        ("高血压并发症的预防", ["高血压"],
         "高血压若控制不好会引起心脏病、脑卒中、肾脏损害等并发症。预防关键：1.规律服药；2.低盐低脂饮食；3.戒烟限酒；4.保持规律运动；5.控制情绪波动。"),
        ("秋季养肺：中医防燥润肺方法", ["节气养生"],
         "秋季燥邪当令，易伤肺阴。养肺食疗推荐：银耳莲子羹、雪梨百合汤、蜂蜜水。穴位保健：按摩合谷、列缺穴。保持室内湿度，减少辛辣食物摄入。"),
        ("慢性病患者如何调节情志", ["心理健康"],
         "情绪波动会影响慢性病控制。中医认为'喜伤心、怒伤肝、忧伤脾、悲伤肺、恐伤肾'。建议：规律作息、培养兴趣爱好、多与家人朋友交流、适当参加社交活动。"),
        ("肾阳虚的表现与调理", ["中医体质"],
         "肾阳虚主要表现：腰膝酸冷、四肢不温、精神不振、面色苍白。调理方法：金匮肾气丸；食疗：韭菜、核桃、羊肉；艾灸：肾俞、命门；避免：寒凉食物、过度劳累。"),
        ("正确使用血糖仪的方法", ["糖尿病"],
         "血糖仪使用注意事项：1.洗净双手后采血；2.采血针穿刺指尖两侧；3.第一滴血擦去；4.试纸不要触摸；5.结果记录备用；6.定期校准仪器；7.妥善存放试纸（避光防潮）。"),
    ]
    pub_at = datetime.now(UTC) - timedelta(days=30)
    for title, tags, body in articles:
        db.add(ContentItem(
            title=title,
            body=body,
            tags=tags,
            status=ContentStatus.PUBLISHED,
            author_id=admin_id,
            published_at=pub_at,
        ))
    await db.flush()
    print(f"  内容库: 补充 {len(articles)} 条文章")


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────
async def main():
    print("=== 开始补充演示数据 ===")
    async with AsyncSessionLocal() as db:
        doctors, patients, admin = await get_users(db)
        archives = await get_archives(db)
        print(f"现有数据：{len(doctors)} 医生，{len(patients)} 患者，{len(archives)} 档案")

        print("\n[1] 量表...")
        await seed_scales(db)
        await seed_scale_records(db, archives)

        print("\n[2] 咨询...")
        await seed_consultations(db, archives, doctors)

        print("\n[3] 宣教...")
        await seed_education(db, archives, doctors)

        print("\n[4] 干预...")
        await seed_interventions(db, archives, doctors)

        print("\n[5] 指导模板...")
        await seed_guidance_templates(db, archives, doctors)

        print("\n[6] 患者标签...")
        await seed_patient_labels(db, archives)

        print("\n[7] 通知...")
        await seed_notifications(db, archives, doctors)

        print("\n[8] 内容库...")
        admin_id = admin.id if admin else (doctors[0].id if doctors else None)
        await seed_content(db, admin_id)

        await db.commit()

    print("\n[9] 系统数据（原生 SQL）...")
    async with AsyncSessionLocal() as db:
        await seed_system_data(db)
        await seed_followup_rules(db)

    print("\n=== 演示数据补充完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
