"""
幂等演示数据 Seed 脚本。
所有 INSERT 使用 ON CONFLICT DO NOTHING 语义（通过 unique 约束 + 查询去重）。

运行方式：
    python scripts/seed_demo.py

DEMO_MODE=true 时由 app/main.py startup 自动调用。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine, Base
from app.models.enums import (
    AlertSeverity, BodyType, ContentStatus, DiseaseType,
    IndicatorType, RecommendationCategory, TaskType, UserRole
)
from app.models.alert import AlertRule
from app.models.constitution import ConstitutionQuestion
from app.models.content import ContentItem
from app.models.followup import FollowupTemplate
from app.models.recommendation import RecommendationTemplate
from app.models.user import User
from app.services.auth_service import hash_password


# ════════════════════════════════════════════════════════
# 1. 体质问卷（60道题，每种体质约8道，部分共用题省略到8题/体质）
# ════════════════════════════════════════════════════════

CONSTITUTION_QUESTIONS: list[dict] = []

_RAW_QUESTIONS = {
    BodyType.BALANCED: [
        ("BAL_01", "您精力充沛吗？", False),
        ("BAL_02", "您容易疲乏吗？", True),
        ("BAL_03", "您说话声音低弱无力吗？", True),
        ("BAL_04", "您感到闷闷不乐、情绪低沉吗？", True),
        ("BAL_05", "您比一般人耐受不了寒冷（冬天的寒冷，夏天的冷空调、电扇等）吗？", True),
        ("BAL_06", "您能适应外界自然和社会环境的变化吗？", False),
        ("BAL_07", "您容易失眠吗？", True),
        ("BAL_08", "您容易忘事（健忘）吗？", True),
    ],
    BodyType.QI_DEFICIENCY: [
        ("QID_01", "您容易疲乏吗？", False),
        ("QID_02", "您容易气短（呼吸短促，接不上气）吗？", False),
        ("QID_03", "您容易心慌吗？", False),
        ("QID_04", "您容易头晕或站起时晕眩吗？", False),
        ("QID_05", "您比别人容易患感冒吗？", False),
        ("QID_06", "您喜欢安静、懒得说话吗？", False),
        ("QID_07", "您说话声音低弱无力吗？", False),
        ("QID_08", "您活动量稍大就容易出虚汗吗？", False),
    ],
    BodyType.YANG_DEFICIENCY: [
        ("YAD_01", "您手脚发凉吗？", False),
        ("YAD_02", "您胃脘部、背部或腰膝部怕冷吗？", False),
        ("YAD_03", "您感到怕冷、衣服比别人穿得多吗？", False),
        ("YAD_04", "您比一般人耐受不了寒冷吗？", False),
        ("YAD_05", "您容易患感冒吗？", False),
        ("YAD_06", "您吃（喝）凉的东西会感到不舒服或者怕吃（喝）凉的东西吗？", False),
        ("YAD_07", "您受凉或吃（喝）凉的东西后，容易腹泻，拉肚子吗？", False),
        ("YAD_08", "您面色苍白或萎黄吗？", False),
    ],
    BodyType.YIN_DEFICIENCY: [
        ("YID_01", "您感到手脚心发热吗？", False),
        ("YID_02", "您感觉身体、脸上发热吗？", False),
        ("YID_03", "您皮肤或口唇干吗？", False),
        ("YID_04", "您口唇的颜色比一般人红吗？", False),
        ("YID_05", "您容易便秘或大便干燥吗？", False),
        ("YID_06", "您面颧部有细微红丝吗？", False),
        ("YID_07", "您感到眼睛干涩吗？", False),
        ("YID_08", "您感到口干咽燥、总想喝水吗？", False),
    ],
    BodyType.PHLEGM_DAMPNESS: [
        ("PHD_01", "您感到胸闷或腹部胀满吗？", False),
        ("PHD_02", "您感到身体沉重不轻松或不爽快吗？", False),
        ("PHD_03", "您腹部肥满松软吗？", False),
        ("PHD_04", "您有额部油脂分泌多的现象吗？", False),
        ("PHD_05", "您上眼睑比别人肿（上眼睑有轻微隆起的现象）吗？", False),
        ("PHD_06", "您嘴里有黏黏的感觉吗？", False),
        ("PHD_07", "您平时痰多，特别是咽喉部总感到有痰堵着吗？", False),
        ("PHD_08", "您舌苔厚腻或有舌苔厚厚的感觉吗？", False),
    ],
    BodyType.DAMP_HEAT: [
        ("DAH_01", "您面部或鼻部有油腻感或油亮发光吗？", False),
        ("DAH_02", "您容易生痤疮或疮疖吗？", False),
        ("DAH_03", "您感到口苦或嘴里有异味吗？", False),
        ("DAH_04", "您大便黏滞不爽、有解不尽的感觉吗？", False),
        ("DAH_05", "您小便时尿道有发热感、尿色浓（深）吗？", False),
        ("DAH_06", "您带下色黄（白带颜色发黄）吗？（限女性回答）", False),
        ("DAH_07", "您的阴囊部位潮湿吗？（限男性回答）", False),
        ("DAH_08", "您大便有臭味吗？", False),
    ],
    BodyType.BLOOD_STASIS: [
        ("BLS_01", "您的皮肤在不知不觉中会出现青紫瘀斑（皮下出血）吗？", False),
        ("BLS_02", "您两颧部有细微红丝吗？", False),
        ("BLS_03", "您身体上有哪里疼痛吗？", False),
        ("BLS_04", "您面色晦暗，或容易出现褐斑吗？", False),
        ("BLS_05", "您容易有黑眼圈吗？", False),
        ("BLS_06", "您容易忘事（健忘）吗？", False),
        ("BLS_07", "您口唇颜色偏暗吗？", False),
        ("BLS_08", "您有牙龈出血的倾向吗？", False),
    ],
    BodyType.QI_STAGNATION: [
        ("QIS_01", "您感到闷闷不乐、情绪低沉吗？", False),
        ("QIS_02", "您容易精神紧张、焦虑不安吗？", False),
        ("QIS_03", "您多愁善感、感情脆弱吗？", False),
        ("QIS_04", "您容易感到害怕或受到惊吓吗？", False),
        ("QIS_05", "您胁肋部或乳房胀痛吗？", False),
        ("QIS_06", "您无缘无故叹气吗？", False),
        ("QIS_07", "您咽喉部有异物感，且吐之不出、咽之不下吗？", False),
        ("QIS_08", "您容易惊恐不安吗？", False),
    ],
    BodyType.SPECIAL_DIATHESIS: [
        ("SPD_01", "您没有感冒时也会打喷嚏吗？", False),
        ("SPD_02", "您没有感冒时也会鼻塞、流鼻涕吗？", False),
        ("SPD_03", "您有因季节变化、温度变化或异味等原因而咳喘的现象吗？", False),
        ("SPD_04", "您容易过敏（对药物、食物、气味、花粉或在季节交替、气候变化时）吗？", False),
        ("SPD_05", "您的皮肤容易起荨麻疹（风团、风疹块、风疙瘩）吗？", False),
        ("SPD_06", "您的皮肤因过敏出现过紫癜（紫红色瘀点、瘀斑）吗？", False),
        ("SPD_07", "您的皮肤一抓就红，并出现抓痕吗？", False),
        ("SPD_08", "您的眼睛容易充血发红（两眼发红）吗？", False),
    ],
}

for bt, qs in _RAW_QUESTIONS.items():
    for seq, (code, content, is_reverse) in enumerate(qs, start=1):
        CONSTITUTION_QUESTIONS.append({
            "code": code,
            "body_type": bt,
            "seq": seq,
            "content": content,
            "is_reverse": is_reverse,
            "options": [
                {"value": 1, "label": "没有"},
                {"value": 2, "label": "很少"},
                {"value": 3, "label": "有时"},
                {"value": 4, "label": "经常"},
                {"value": 5, "label": "总是"},
            ],
        })


# ════════════════════════════════════════════════════════
# 2. 调护建议模板（9体质 × 主要病种，按5类分组）
# ════════════════════════════════════════════════════════

RECOMMENDATION_TEMPLATES: list[dict] = []

_TEMPLATES_DATA = {
    BodyType.BALANCED: {
        None: [  # 无特定病种
            (RecommendationCategory.DAILY_ROUTINE, "规律作息", "保持早睡早起的规律作息，每天7-8小时睡眠，避免熬夜。"),
            (RecommendationCategory.DIET, "均衡饮食", "饮食多样化，五谷杂粮、蔬菜水果均衡摄入，避免暴饮暴食。"),
            (RecommendationCategory.EXERCISE, "适量运动", "每天保持30分钟以上的有氧运动，如快走、游泳、太极拳等。"),
            (RecommendationCategory.EMOTIONAL, "情志调畅", "保持积极乐观心态，适当参加社交活动，定期放松减压。"),
            (RecommendationCategory.EXTERNAL, "日常保健", "可适当进行穴位按摩，如按摩足三里、关元等保健穴位。"),
        ],
    },
    BodyType.QI_DEFICIENCY: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "充足休息", "保证充足睡眠，避免过度劳累，饭后不宜立即活动。"),
            (RecommendationCategory.DIET, "益气健脾饮食", "多食用山药、大枣、黄芪、党参等益气补脾食物；避免生冷寒凉食物。"),
            (RecommendationCategory.EXERCISE, "柔和运动", "适合八段锦、太极拳等柔和运动，避免大量出汗和剧烈运动。"),
            (RecommendationCategory.EMOTIONAL, "避免劳神", "避免思虑过多，保持心情舒畅，减少不必要的担忧和紧张。"),
            (RecommendationCategory.EXTERNAL, "艾灸保健", "可灸足三里、气海、关元等穴，每穴10-15分钟，每周2-3次。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "低盐益气饮食", "气虚高血压患者需低盐饮食（每日<6g），同时补充益气食物如黄芪粥。"),
            (RecommendationCategory.EXERCISE, "温和降压运动", "建议散步、太极拳，运动中注意监测血压，避免突然用力动作。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "益气控糖饮食", "选择低GI食物，多食南瓜、山药（注意适量）、苦瓜等，少量多餐。"),
            (RecommendationCategory.EXERCISE, "餐后缓和运动", "餐后1小时进行15-20分钟散步，有助于降低餐后血糖，气虚患者不宜过度。"),
        ],
    },
    BodyType.YANG_DEFICIENCY: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "避寒保暖", "注意防寒保暖，尤其腰腹部和足部；夏季避免长时间待在空调房间。"),
            (RecommendationCategory.DIET, "温阳散寒饮食", "多食羊肉、韭菜、生姜、肉桂等温阳食物；忌食生冷瓜果和凉性食物。"),
            (RecommendationCategory.EXERCISE, "温和运动生阳", "适合在阳光充足时段进行户外运动，如慢跑、八段锦；避免冬季早起锻炼。"),
            (RecommendationCategory.EMOTIONAL, "积极乐观", "阳虚体质者容易精神萎靡，需主动参与社交，保持积极心态。"),
            (RecommendationCategory.EXTERNAL, "泡脚温阳", "每晚用生姜、艾叶温水泡脚20-30分钟，可加强阳气；艾灸命门、神阙穴。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "温阳低盐饮食", "阳虚高血压需低盐饮食，可适当食用温阳食物，但避免过于燥热。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "温阳控糖饮食", "阳虚糖尿病患者饮食偏温，选择温性低GI食物，避免冷饮和冷食。"),
        ],
    },
    BodyType.YIN_DEFICIENCY: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "避免熬夜", "阴虚者宜早睡，晚上11点前入睡，午休30分钟，避免夜间过度用脑。"),
            (RecommendationCategory.DIET, "滋阴润燥饮食", "多食银耳、百合、枸杞、黑芝麻等滋阴食物；少食辛辣煎炸和羊肉等温热食物。"),
            (RecommendationCategory.EXERCISE, "舒缓运动", "适合游泳、太极拳、瑜伽等舒缓运动，避免大量出汗。"),
            (RecommendationCategory.EMOTIONAL, "平静心态", "阴虚者易急躁，学习冥想、深呼吸；避免情绪激动和长期紧张状态。"),
            (RecommendationCategory.EXTERNAL, "穴位滋阴", "按摩三阴交、太溪穴，每穴5分钟；避免艾灸（火性伤阴）。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "滋阴降压饮食", "阴虚高血压宜多食芹菜、菊花茶、莲子心茶等，有助于滋阴降压。"),
            (RecommendationCategory.EXERCISE, "静养运动", "推荐太极拳、八段锦，运动强度不宜过大，注意监测血压。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "滋阴控糖饮食", "阴虚糖尿病患者多口渴，饮水充足，选择滋阴低糖食物，如苦瓜、山药。"),
        ],
    },
    BodyType.PHLEGM_DAMPNESS: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "规律起居除湿", "保持室内干燥通风；饮食规律，不可过饱；坚持锻炼改善体质。"),
            (RecommendationCategory.DIET, "化痰利湿饮食", "多食薏苡仁、冬瓜、赤小豆、白扁豆等化湿食物；忌肥甘厚腻、甜食和酒。"),
            (RecommendationCategory.EXERCISE, "有氧减重运动", "痰湿体质宜加强有氧运动，如快走、游泳；运动量可适当增大以促进代谢。"),
            (RecommendationCategory.EMOTIONAL, "开朗心态", "保持开朗，避免思虑过多；多参加户外活动改善痰湿状态。"),
            (RecommendationCategory.EXTERNAL, "刮痧除湿", "可对背部膀胱经进行刮痧，或艾灸丰隆、脾俞穴，化痰除湿。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "化痰降压饮食", "痰湿高血压需严格限盐，多食化痰降压食物如芹菜、荷叶茶、海带。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "化湿控糖饮食", "痰湿糖尿病患者需控制主食量，选择低GI粗粮，避免甜食，多食苦瓜。"),
            (RecommendationCategory.EXERCISE, "减重运动", "痰湿糖尿病患者减重意义重大，建议每天有氧运动45-60分钟。"),
        ],
    },
    BodyType.DAMP_HEAT: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "清洁规律作息", "保持皮肤清洁；避免熬夜，保持规律作息；室内保持通风。"),
            (RecommendationCategory.DIET, "清热利湿饮食", "多食苦瓜、绿豆、薏苡仁、冬瓜；忌辛辣、油腻、烟酒。"),
            (RecommendationCategory.EXERCISE, "适量运动清热", "适合游泳、跑步等有氧运动；选择早晚凉爽时段运动，避免暑热。"),
            (RecommendationCategory.EMOTIONAL, "心平气和", "湿热体质者易急躁，学习控制情绪，避免发怒和激动。"),
            (RecommendationCategory.EXTERNAL, "拔罐祛湿", "可在背部进行拔罐或刮痧祛湿；清热穴位按摩：曲池、合谷。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "清热降压饮食", "湿热高血压宜食菊花茶、苦丁茶；严格低盐，忌辛辣刺激。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "清热控糖饮食", "湿热糖尿病多口苦口干，饮茶可选苦瓜茶、荷叶茶；控制主食量。"),
        ],
    },
    BodyType.BLOOD_STASIS: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "规律活动防瘀", "避免久坐久卧，每坐1小时起来活动；保持温暖，避免受寒。"),
            (RecommendationCategory.DIET, "活血化瘀饮食", "多食山楂、红花、丹参、桃仁（需医生指导）、玫瑰花茶；避免寒凉食物。"),
            (RecommendationCategory.EXERCISE, "有氧活血运动", "适合太极拳、八段锦、散步等促进血液循环的运动，持续坚持。"),
            (RecommendationCategory.EMOTIONAL, "舒畅情志", "血瘀与情志不畅相关，保持心情舒畅，避免抑郁和忧愁。"),
            (RecommendationCategory.EXTERNAL, "活血按摩", "按摩血海、膈俞穴，每穴5分钟；玫瑰精油按摩促进循环。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "活血降压饮食", "血瘀高血压宜食山楂（注意量）、红曲米；低盐饮食，避免高脂。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "活血控糖饮食", "血瘀糖尿病注意饮食清淡，多食活血蔬菜如洋葱、黑木耳，控制总热量。"),
        ],
    },
    BodyType.QI_STAGNATION: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "规律生活舒郁", "保持规律作息，避免独处；多参与社交和集体活动，转移注意力。"),
            (RecommendationCategory.DIET, "疏肝理气饮食", "多食玫瑰花茶、陈皮、金橘、柑橘类；少饮酒精；忌生冷寒凉。"),
            (RecommendationCategory.EXERCISE, "舒展运动", "适合户外运动、太极拳、瑜伽；运动时注重调整呼吸，放松身心。"),
            (RecommendationCategory.EMOTIONAL, "情志疏导", "学习情绪管理，通过倾诉、日记、冥想等方式宣泄情绪。"),
            (RecommendationCategory.EXTERNAL, "芳香疗法", "玫瑰、薰衣草精油按摩太冲、期门穴；香薰有助于放松情志。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.EMOTIONAL, "情志降压", "气郁高血压与情绪密切相关，学习压力管理技巧，减少精神紧张。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.EMOTIONAL, "减压控糖", "气郁糖尿病患者需关注心理状态，情绪波动会影响血糖，学习减压放松。"),
        ],
    },
    BodyType.SPECIAL_DIATHESIS: {
        None: [
            (RecommendationCategory.DAILY_ROUTINE, "规避过敏原", "了解并避开个人过敏原；室内定期清洁，减少尘螨；花粉季佩戴口罩。"),
            (RecommendationCategory.DIET, "益气固表饮食", "多食固表抗敏食物如蜂蜜（少量）、大枣、黄芪；避免已知过敏食物。"),
            (RecommendationCategory.EXERCISE, "温和运动提免疫", "适合游泳、太极拳；运动强度适中，有助于增强免疫力和适应能力。"),
            (RecommendationCategory.EMOTIONAL, "平稳心态", "保持心态平稳，减少焦虑；过敏发作时不慌张，按医嘱处理。"),
            (RecommendationCategory.EXTERNAL, "穴位固表", "按摩迎香、足三里穴，有助于固表防敏；艾灸命门增强正气。"),
        ],
        DiseaseType.HYPERTENSION: [
            (RecommendationCategory.DIET, "抗敏降压饮食", "特禀质高血压需注意食物过敏，低盐饮食，记录饮食日记追踪过敏反应。"),
        ],
        DiseaseType.DIABETES_T2: [
            (RecommendationCategory.DIET, "抗敏控糖饮食", "特禀质糖尿病患者选择食物需谨慎，低GI食物同时注意避开过敏食物。"),
        ],
    },
}

for bt, disease_map in _TEMPLATES_DATA.items():
    for dt, items in disease_map.items():
        for i, (cat, title, content) in enumerate(items):
            RECOMMENDATION_TEMPLATES.append({
                "body_type": bt,
                "disease_type": dt,
                "category": cat,
                "title": title,
                "content": content,
                "priority": len(items) - i,
            })


# ════════════════════════════════════════════════════════
# 3. 随访计划模板
# ════════════════════════════════════════════════════════

FOLLOWUP_TEMPLATES = [
    {
        "name": "高血压30天随访计划",
        "disease_type": DiseaseType.HYPERTENSION,
        "duration_days": 30,
        "tasks": [
            {
                "task_type": TaskType.INDICATOR_REPORT.value,
                "name": "记录血压（晨起）",
                "required": True,
                "every_day": True,
                "meta": {"indicator_type": IndicatorType.BLOOD_PRESSURE.value, "scene": "morning"},
            },
            {
                "task_type": TaskType.INDICATOR_REPORT.value,
                "name": "记录血压（睡前）",
                "required": True,
                "every_day": True,
                "meta": {"indicator_type": IndicatorType.BLOOD_PRESSURE.value, "scene": "evening"},
            },
            {
                "task_type": TaskType.EXERCISE.value,
                "name": "适量运动30分钟",
                "required": False,
                "every_day": True,
                "meta": {},
            },
            {
                "task_type": TaskType.MEDICATION.value,
                "name": "按时服用降压药",
                "required": True,
                "every_day": True,
                "meta": {},
            },
        ],
    },
    {
        "name": "2型糖尿病30天随访计划",
        "disease_type": DiseaseType.DIABETES_T2,
        "duration_days": 30,
        "tasks": [
            {
                "task_type": TaskType.INDICATOR_REPORT.value,
                "name": "记录空腹血糖",
                "required": True,
                "every_day": True,
                "meta": {"indicator_type": IndicatorType.BLOOD_GLUCOSE.value, "scene": "fasting"},
            },
            {
                "task_type": TaskType.INDICATOR_REPORT.value,
                "name": "记录餐后2小时血糖",
                "required": True,
                "every_day": True,
                "meta": {"indicator_type": IndicatorType.BLOOD_GLUCOSE.value, "scene": "postmeal_2h"},
            },
            {
                "task_type": TaskType.EXERCISE.value,
                "name": "餐后散步20分钟",
                "required": False,
                "every_day": True,
                "meta": {},
            },
            {
                "task_type": TaskType.MEDICATION.value,
                "name": "按时服用降糖药",
                "required": True,
                "every_day": True,
                "meta": {},
            },
        ],
    },
]


# ════════════════════════════════════════════════════════
# 4. 预警规则
# ════════════════════════════════════════════════════════

ALERT_RULES = [
    {
        "name": "血压收缩压重度升高",
        "indicator_type": IndicatorType.BLOOD_PRESSURE,
        "severity": AlertSeverity.HIGH,
        "conditions": [{"field": "systolic", "op": ">", "value": 180}],
        "message_template": "⚠️ 警报：收缩压 {systolic} mmHg，严重超标！请立即就医或联系随访医生。",
    },
    {
        "name": "血压舒张压重度升高",
        "indicator_type": IndicatorType.BLOOD_PRESSURE,
        "severity": AlertSeverity.HIGH,
        "conditions": [{"field": "diastolic", "op": ">", "value": 120}],
        "message_template": "⚠️ 警报：舒张压 {diastolic} mmHg，严重超标！请立即就医。",
    },
    {
        "name": "血压收缩压中度升高",
        "indicator_type": IndicatorType.BLOOD_PRESSURE,
        "severity": AlertSeverity.MEDIUM,
        "conditions": [
            {"field": "systolic", "op": ">", "value": 160},
            {"field": "systolic", "op": "<=", "value": 180},
        ],
        "message_template": "⚠️ 提示：收缩压 {systolic} mmHg，偏高，请注意休息，联系医生评估用药。",
    },
    {
        "name": "空腹血糖危急升高",
        "indicator_type": IndicatorType.BLOOD_GLUCOSE,
        "severity": AlertSeverity.HIGH,
        "conditions": [{"field": "value", "op": ">", "value": 16.7}],
        "message_template": "⚠️ 警报：空腹血糖 {value} mmol/L，严重超标！请立即就医。",
    },
    {
        "name": "空腹血糖偏高",
        "indicator_type": IndicatorType.BLOOD_GLUCOSE,
        "severity": AlertSeverity.MEDIUM,
        "conditions": [
            {"field": "value", "op": ">", "value": 7.0},
            {"field": "value", "op": "<=", "value": 16.7},
        ],
        "message_template": "⚠️ 提示：空腹血糖 {value} mmol/L，高于正常值，请联系医生调整治疗方案。",
    },
    {
        "name": "血糖过低预警",
        "indicator_type": IndicatorType.BLOOD_GLUCOSE,
        "severity": AlertSeverity.HIGH,
        "conditions": [{"field": "value", "op": "<", "value": 3.9}],
        "message_template": "⚠️ 低血糖警报：血糖 {value} mmol/L，请立即补充糖分并就医！",
    },
]


# ════════════════════════════════════════════════════════
# 5. 示例文章（5篇）
# ════════════════════════════════════════════════════════

SAMPLE_ARTICLES = [
    {
        "title": "高血压患者的日常血压管理指南",
        "summary": "了解如何正确测量血压、识别危险信号，以及日常生活中的血压管理技巧。",
        "body": """## 正确测量血压

正确测量血压是高血压管理的第一步。建议遵循"722"原则：
- **7**天：连续测量7天
- **2**次：早晚各测量一次
- **2**分钟：测量前静坐2分钟

## 血压正常值
- 正常：<120/80 mmHg
- 高血压1级：140-159/90-99 mmHg
- 高血压2级：160-179/100-109 mmHg
- 高血压危象：≥180/120 mmHg

## 红旗症状
出现以下症状请立即就医：
- 剧烈头痛、视力模糊
- 胸痛、呼吸困难
- 言语不清、肢体无力

## 日常管理建议
1. 低盐饮食（每日<6g食盐）
2. 戒烟限酒
3. 控制体重
4. 规律运动
5. 按时服药

> ⚠️ 本文仅供参考，具体治疗方案请遵医嘱。""",
        "tags": ["高血压", "血压管理", "慢病"],
    },
    {
        "title": "糖尿病饮食管理：吃对食物控血糖",
        "summary": "科学的饮食搭配是控制血糖的重要基础，了解GI值和饮食原则帮助您更好地管理糖尿病。",
        "body": """## 什么是血糖指数（GI）

血糖指数（GI）是衡量食物升糖速度的指标。
- **低GI（<55）**：燕麦、全麦面包、大多数蔬菜
- **中GI（55-70）**：普通米饭、玉米
- **高GI（>70）**：白面包、糯米、蜂蜜

## 糖尿病饮食黄金原则

**限制总热量**：根据体重和活动量制定每日热量目标。

**控制主食量**：每餐主食约一个拳头大小（50-75g干重）。

**增加蔬菜摄入**：每餐蔬菜占盘子的一半以上，优选绿叶菜。

**优质蛋白**：鱼、鸡蛋、豆制品、瘦肉，减少红肉摄入。

## 推荐食物
✅ 苦瓜、黄瓜、芹菜
✅ 燕麦、荞麦
✅ 黑木耳、洋葱

## 避免食物
❌ 含糖饮料、果汁
❌ 白米饭、白面条（可适量）
❌ 蛋糕、糖果、饼干

> ⚠️ 饮食方案需个体化，建议在营养师指导下制定。""",
        "tags": ["糖尿病", "饮食管理", "血糖控制"],
    },
    {
        "title": "八段锦：古老导引术的现代养生价值",
        "summary": "八段锦是一套传统的健身气功，简单易学，适合各年龄段人群，尤其对慢病患者有独特价值。",
        "body": """## 八段锦简介

八段锦是中国传统导引养生功法之一，历史悠久，由八节动作组成，形如绸缎般柔美舒展，故名"八段锦"。

## 八式动作

1. **两手托天理三焦** - 双手向上托举，拉伸脊柱，调理三焦
2. **左右开弓似射雕** - 拉弓射箭姿势，强化胸背肌群
3. **调理脾胃须单举** - 单手上托，调理脾胃功能
4. **五劳七伤往后瞧** - 转头后瞧，活动颈部，消除疲劳
5. **摇头摆尾去心火** - 俯身摇摆，降心火，安定心神
6. **两手攀足固肾腰** - 弯腰攀足，强腰固肾
7. **攒拳怒目增气力** - 握拳出击，增强气力
8. **背后七颠百病消** - 提踵颠足，振动全身

## 适合人群
- 高血压、糖尿病慢病患者
- 气虚、阳虚体质人群
- 办公室久坐人群

## 练习建议
每天早晨练习1-2遍，约15-20分钟。动作宜缓慢柔和，配合自然呼吸。

> 💡 建议在专业老师指导下学习，确保动作规范。""",
        "tags": ["八段锦", "导引功", "运动养生", "治未病"],
    },
    {
        "title": "痰湿体质的辨识与调护",
        "summary": "痰湿体质在现代都市人群中十分常见，了解痰湿体质的特征和调护方法，助您回归健康。",
        "body": """## 痰湿体质的主要表现

**外形特征**：
- 体形偏胖，腹部肥满松软
- 面部油腻，额头出油多

**常见症状**：
- 身体困重，总感觉不清爽
- 口中黏腻，痰多
- 舌苔厚腻
- 容易困倦，嗜睡

## 痰湿体质的形成原因

1. **饮食不节**：长期过食肥甘厚腻
2. **缺乏运动**：代谢缓慢，水湿聚积
3. **脾胃虚弱**：运化失职，痰湿内生

## 调护方案

**饮食调护**：
- ✅ 推荐：薏苡仁、冬瓜、赤小豆、白扁豆、山楂
- ❌ 忌食：油腻、甜食、酒类、奶油制品

**运动调护**：
加大运动量是痰湿体质的关键！建议：
- 每天有氧运动45-60分钟
- 快走、游泳、骑车
- 坚持出汗可促进湿气排出

**外治调护**：
- 刮痧：背部膀胱经
- 艾灸：丰隆、脾俞、足三里

## 注意事项
痰湿体质易发高血压、高脂血症、糖尿病，需定期体检，积极干预。""",
        "tags": ["痰湿体质", "体质养生", "治未病"],
    },
    {
        "title": "气虚体质：认识「总感觉累」背后的体质原因",
        "summary": "经常感到疲乏、气短、容易感冒？你可能是气虚体质。了解气虚的成因和调护方法。",
        "body": """## 气虚体质的典型表现

如果您经常有以下感受，可能是气虚体质：
- 疲乏，稍微活动就累
- 说话有气无力，声音低弱
- 容易气短，呼吸接不上
- 动不动就出虚汗
- 反复感冒，抵抗力差

## 气虚的中医解读

中医认为，"气"是生命活动的基本动力。气虚则全身机能低下，表现为：
- **卫气不固**：外邪容易入侵→频繁感冒
- **脾气虚弱**：消化功能差→食欲减退
- **心气不足**：心脏动力不足→心慌气短

## 气虚调护方案

**饮食益气**：
- 黄芪粥：黄芪30g煎汤，加入大米熬粥
- 大枣茶：每天3-5颗红枣，煮水代茶饮
- 山药炖排骨：健脾益气的经典食疗

**运动调护**：
选择动作柔和的运动，不宜剧烈：
- 八段锦（每天早晨）
- 太极拳
- 散步（30分钟/天）

**艾灸保健**：
灸足三里、气海、关元穴，每次各10-15分钟，每周2-3次，持续补气。

## 预防感冒技巧
- 天气变化时及时增减衣物
- 人群密集场所戴口罩
- 保持室内通风，避免交叉感染

> 💊 气虚明显者，可在中医师指导下服用玉屏风散等补气中药。""",
        "tags": ["气虚体质", "体质养生", "治未病", "益气"],
    },
]


# ════════════════════════════════════════════════════════
# 6. 演示账号
# ════════════════════════════════════════════════════════

DEMO_USERS = [
    {"phone": "admin@tcm", "name": "管理员", "password": "Demo@123456", "role": UserRole.ADMIN},
    {"phone": "doctor@tcm", "name": "张医生", "password": "Demo@123456", "role": UserRole.PROFESSIONAL},
    {"phone": "patient@tcm", "name": "李患者", "password": "Demo@123456", "role": UserRole.PATIENT},
]


# ════════════════════════════════════════════════════════
# Seed 执行函数（幂等）
# ════════════════════════════════════════════════════════

async def seed_questions(db: AsyncSession):
    for q_data in CONSTITUTION_QUESTIONS:
        existing = await db.execute(
            select(ConstitutionQuestion).where(ConstitutionQuestion.code == q_data["code"])
        )
        if existing.scalar_one_or_none() is not None:
            continue
        q = ConstitutionQuestion(
            code=q_data["code"],
            body_type=q_data["body_type"],
            seq=q_data["seq"],
            content=q_data["content"],
            options=q_data["options"],
            is_reverse=q_data["is_reverse"],
        )
        db.add(q)
    await db.flush()
    print(f"  ✓ 体质问卷：{len(CONSTITUTION_QUESTIONS)} 题")


async def seed_recommendation_templates(db: AsyncSession):
    count = 0
    for t_data in RECOMMENDATION_TEMPLATES:
        existing = await db.execute(
            select(RecommendationTemplate).where(
                RecommendationTemplate.body_type == t_data["body_type"],
                RecommendationTemplate.category == t_data["category"],
                RecommendationTemplate.title == t_data["title"],
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        t = RecommendationTemplate(
            body_type=t_data["body_type"],
            disease_type=t_data["disease_type"],
            category=t_data["category"],
            title=t_data["title"],
            content=t_data["content"],
            priority=t_data["priority"],
        )
        db.add(t)
        count += 1
    await db.flush()
    print(f"  ✓ 调护建议模板：{count} 条新增")


async def seed_followup_templates(db: AsyncSession):
    count = 0
    for ft_data in FOLLOWUP_TEMPLATES:
        existing = await db.execute(
            select(FollowupTemplate).where(FollowupTemplate.name == ft_data["name"])
        )
        if existing.scalar_one_or_none() is not None:
            continue
        ft = FollowupTemplate(
            name=ft_data["name"],
            disease_type=ft_data["disease_type"],
            duration_days=ft_data["duration_days"],
            tasks=ft_data["tasks"],
        )
        db.add(ft)
        count += 1
    await db.flush()
    print(f"  ✓ 随访计划模板：{count} 条新增")


async def seed_alert_rules(db: AsyncSession):
    count = 0
    for ar_data in ALERT_RULES:
        existing = await db.execute(
            select(AlertRule).where(AlertRule.name == ar_data["name"])
        )
        if existing.scalar_one_or_none() is not None:
            continue
        ar = AlertRule(
            name=ar_data["name"],
            indicator_type=ar_data["indicator_type"],
            severity=ar_data["severity"],
            conditions=ar_data["conditions"],
            message_template=ar_data["message_template"],
            is_active=True,
        )
        db.add(ar)
        count += 1
    await db.flush()
    print(f"  ✓ 预警规则：{count} 条新增")


async def seed_articles(db: AsyncSession, author_id):
    count = 0
    for art_data in SAMPLE_ARTICLES:
        existing = await db.execute(
            select(ContentItem).where(ContentItem.title == art_data["title"])
        )
        if existing.scalar_one_or_none() is not None:
            continue
        from datetime import datetime, timezone
        art = ContentItem(
            title=art_data["title"],
            summary=art_data["summary"],
            body=art_data["body"],
            tags=art_data["tags"],
            author_id=author_id,
            status=ContentStatus.PUBLISHED,
            reviewed_by_id=author_id,
            published_at=datetime.now(timezone.utc),
        )
        db.add(art)
        count += 1
    await db.flush()
    print(f"  ✓ 示例文章：{count} 篇新增")


async def seed_users(db: AsyncSession):
    users = {}
    for u_data in DEMO_USERS:
        existing = await db.execute(
            select(User).where(User.phone == u_data["phone"])
        )
        user = existing.scalar_one_or_none()
        if user is None:
            user = User(
                phone=u_data["phone"],
                name=u_data["name"],
                password_hash=hash_password(u_data["password"]),
                role=u_data["role"],
            )
            db.add(user)
            await db.flush()
            print(f"  ✓ 账号创建：{u_data['name']} ({u_data['phone']})")
        users[u_data["role"]] = user
    return users


async def run_seed():
    print("🌱 开始 Seed 演示数据...")
    # 确保表已创建（SQLite 演示时无需单独跑 Alembic）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        try:
            users = await seed_users(db)
            admin_user = users.get(UserRole.ADMIN)
            await seed_questions(db)
            await seed_recommendation_templates(db)
            await seed_followup_templates(db)
            await seed_alert_rules(db)
            if admin_user:
                await seed_articles(db, admin_user.id)
            await db.commit()
            print("✅ Seed 完成！")
            print("\n演示账号（密码均为 Demo@123456）：")
            for u_data in DEMO_USERS:
                print(f"  {u_data['role'].value:<15} {u_data['phone']}")
        except Exception as e:
            await db.rollback()
            print(f"❌ Seed 失败: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(run_seed())
