"""
50名患者全量数据 Seed 脚本

运行方式：
    python scripts/seed_50_patients.py

幂等：按 phone 去重，已存在则跳过。
新增内容：30名患者 + 8个家庭档案 + 完整健康档案 + 慢病记录 + 指标数据 + 标签关联
"""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app.models  # noqa: F401 — 注册所有模型，确保 FK 解析正常
import app.models.org  # noqa: F401 — organizations 表（未在 __init__ 注册）
import app.models.config  # noqa: F401
import app.models.clinical  # noqa: F401
import app.models.sysdict  # noqa: F401
import app.models.guidance  # noqa: F401

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.archive import PatientArchive, FamilyArchive, ArchiveFamilyMember
from app.models.health import HealthProfile, ChronicDiseaseRecord, HealthIndicator
from app.models.label import LabelCategory, Label, PatientLabel
from app.models.enums import (
    ArchiveType, IdType, DiseaseType, IndicatorType
)

# ─────────────────────────────────────────────────────────────────────────────
# 患者数据定义（30名，覆盖全部档案类型）
# ─────────────────────────────────────────────────────────────────────────────

PATIENTS = [
    # ── ELDERLY (老年人 60+) ──────────────────────────────────────────────
    {
        "name": "吴振国", "gender": "male",
        "birth_date": date(1952, 3, 15), "ethnicity": "汉族",
        "occupation": "退休教师",
        "id_number": "110105195203152317", "phone": "15501234001",
        "phone2": "15501234002", "email": "wuzg@example.com",
        "province": "北京市", "city": "北京市", "district": "朝阳区",
        "address": "朝阳区劲松路27号院3单元502室",
        "emergency_contact_name": "吴明月", "emergency_contact_phone": "13801234001",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["高血压", "糖尿病", "痰湿质"],
        "past_history": ["原发性高血压（2008年确诊）", "2型糖尿病（2013年确诊）", "腰椎间盘突出（2019年手术）"],
        "family_history": ["父亲：高血压、脑卒中", "母亲：糖尿病"],
        "allergy_history": ["青霉素过敏（皮疹）"],
        "notes": "患者依从性良好，规律服药，每月复诊。需重点监测血糖和血压。",
        "has_hypertension": True, "has_diabetes": True,
        "height": 172, "weight": 82, "waist": 98,
        "smoking": "former", "drinking": "former", "exercise": "occasional",
        "sleep": 6.5, "stress": "medium",
        "bp_readings": [(158, 95), (152, 90), (148, 88)],
        "glucose_readings": [(7.8, "fasting"), (10.2, "postmeal_2h"), (7.2, "fasting")],
    },
    {
        "name": "沈淑英", "gender": "female",
        "birth_date": date(1958, 7, 22), "ethnicity": "汉族",
        "occupation": "退休工人",
        "id_number": "310112195807223428", "phone": "15501234003",
        "province": "上海市", "city": "上海市", "district": "徐汇区",
        "address": "徐汇区漕溪路158号5楼",
        "emergency_contact_name": "沈建辉", "emergency_contact_phone": "13801234003",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["高血压", "气虚质", "规律随访"],
        "past_history": ["原发性高血压（2010年确诊）", "慢性胃炎（2015年）"],
        "family_history": ["父亲：高血压", "姐姐：高血压"],
        "allergy_history": ["磺胺类药物过敏"],
        "notes": "气虚质明显，平时易疲劳、气短。建议中医调理配合规律用药。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 158, "weight": 65, "waist": 88,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 7.0, "stress": "low",
        "bp_readings": [(145, 88), (140, 85), (138, 82)],
        "glucose_readings": [(5.2, "fasting")],
    },
    {
        "name": "梅国华", "gender": "male",
        "birth_date": date(1948, 11, 8), "ethnicity": "汉族",
        "occupation": "退休干部",
        "id_number": "440103194811083515", "phone": "15501234005",
        "province": "广东省", "city": "广州市", "district": "越秀区",
        "address": "越秀区东风中路99号嘉业大厦8楼",
        "emergency_contact_name": "梅晓丽", "emergency_contact_phone": "13801234005",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["冠心病", "高血压", "血瘀质", "高风险"],
        "past_history": ["冠心病（2005年确诊，2008年放置支架）", "原发性高血压（2003年确诊）", "阑尾炎手术（1975年）"],
        "family_history": ["父亲：冠心病，65岁去世", "母亲：高血压"],
        "allergy_history": ["阿司匹林过敏（胃肠道反应）"],
        "notes": "冠心病史，长期服用他汀类药物及抗血板药。需警惕心绞痛发作，避免剧烈运动。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 168, "weight": 75, "waist": 93,
        "smoking": "former", "drinking": "current", "exercise": "occasional",
        "sleep": 5.5, "stress": "high",
        "bp_readings": [(162, 98), (158, 94), (155, 92)],
        "glucose_readings": [(5.8, "fasting")],
    },
    {
        "name": "龚桂芳", "gender": "female",
        "birth_date": date(1953, 5, 31), "ethnicity": "汉族",
        "occupation": "退休会计",
        "id_number": "320106195305314829", "phone": "15501234007",
        "province": "江苏省", "city": "南京市", "district": "鼓楼区",
        "address": "鼓楼区中山路256号天华大厦3楼302",
        "emergency_contact_name": "褚永年", "emergency_contact_phone": "15501234009",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["糖尿病", "慢阻肺", "痰湿质"],
        "past_history": ["2型糖尿病（2011年确诊）", "慢性阻塞性肺疾病（2017年确诊）", "胆囊切除术（2002年）"],
        "family_history": ["母亲：糖尿病", "父亲：肺气肿"],
        "allergy_history": ["无已知过敏史"],
        "notes": "痰湿质，体型偏胖，呼吸功能下降。建议减重配合呼吸康复训练。",
        "has_hypertension": False, "has_diabetes": True,
        "height": 155, "weight": 72, "waist": 95,
        "smoking": "never", "drinking": "never", "exercise": "never",
        "sleep": 8.0, "stress": "low",
        "bp_readings": [(130, 80), (128, 78)],
        "glucose_readings": [(8.5, "fasting"), (12.1, "postmeal_2h"), (8.2, "fasting")],
    },
    {
        "name": "褚永年", "gender": "male",
        "birth_date": date(1944, 9, 14), "ethnicity": "汉族",
        "occupation": "退休",
        "id_number": "320106194409143618", "phone": "15501234009",
        "province": "江苏省", "city": "南京市", "district": "鼓楼区",
        "address": "鼓楼区中山路256号天华大厦3楼302",
        "emergency_contact_name": "龚桂芳", "emergency_contact_phone": "15501234007",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["高血压", "脑卒中", "阳虚质", "高风险"],
        "past_history": ["脑卒中（2018年，左侧肢体轻度偏瘫后遗症）", "原发性高血压（1998年确诊）", "前列腺增生（2016年）"],
        "family_history": ["父亲：高血压、脑出血", "兄弟：高血压"],
        "allergy_history": ["青霉素过敏", "头孢类抗生素过敏"],
        "notes": "脑卒中后遗症期，左侧肢体功能部分受损，行走需扶助。需密切监测血压，防止再次卒中。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 170, "weight": 68, "waist": 89,
        "smoking": "former", "drinking": "never", "exercise": "occasional",
        "sleep": 7.0, "stress": "medium",
        "bp_readings": [(168, 100), (162, 96), (158, 94)],
        "glucose_readings": [(5.6, "fasting")],
    },
    {
        "name": "卫秀英", "gender": "female",
        "birth_date": date(1960, 2, 28), "ethnicity": "汉族",
        "occupation": "退休护士",
        "id_number": "110108196002284528", "phone": "15501234011",
        "province": "北京市", "city": "北京市", "district": "海淀区",
        "address": "海淀区学院路甲5号枫丹白露小区12栋1单元",
        "emergency_contact_name": "吴振国", "emergency_contact_phone": "15501234001",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["高血压", "阴虚质", "规律随访"],
        "past_history": ["原发性高血压（2012年确诊）", "更年期综合征（已缓解）", "子宫肌瘤（2008年手术切除）"],
        "family_history": ["母亲：高血压", "姐姐：糖尿病"],
        "allergy_history": ["无已知过敏史"],
        "notes": "阴虚质明显，潮热盗汗基本缓解。血压控制良好，继续维持原方案。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 160, "weight": 58, "waist": 80,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 6.0, "stress": "medium",
        "bp_readings": [(138, 85), (135, 82), (132, 80)],
        "glucose_readings": [(5.0, "fasting")],
    },
    {
        "name": "项国强", "gender": "male",
        "birth_date": date(1955, 8, 17), "ethnicity": "汉族",
        "occupation": "退休厂长",
        "id_number": "330106195508172413", "phone": "15501234013",
        "province": "浙江省", "city": "杭州市", "district": "西湖区",
        "address": "西湖区文三路478号西子花园小区B幢",
        "emergency_contact_name": "项小燕", "emergency_contact_phone": "13801234013",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["糖尿病", "痰湿质", "中风险"],
        "past_history": ["2型糖尿病（2009年确诊）", "高脂血症（2012年）", "慢性胃炎"],
        "family_history": ["父亲：糖尿病", "母亲：高血压"],
        "allergy_history": ["花粉过敏（春季鼻炎）"],
        "notes": "体型肥胖，痰湿质。血糖控制一般，建议加强饮食干预，减少精制碳水摄入。",
        "has_hypertension": False, "has_diabetes": True,
        "height": 175, "weight": 92, "waist": 106,
        "smoking": "current", "drinking": "current", "exercise": "never",
        "sleep": 7.5, "stress": "medium",
        "bp_readings": [(128, 80), (130, 82)],
        "glucose_readings": [(9.2, "fasting"), (13.5, "postmeal_2h"), (8.9, "fasting")],
    },
    {
        "name": "赵桂珍", "gender": "female",
        "birth_date": date(1950, 4, 6), "ethnicity": "汉族",
        "occupation": "退休",
        "id_number": "210103195004064821", "phone": "15501234015",
        "province": "辽宁省", "city": "沈阳市", "district": "和平区",
        "address": "和平区南京南街399号幸福小区6栋",
        "emergency_contact_name": "赵国栋", "emergency_contact_phone": "13801234015",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.ELDERLY,
        "tags": ["冠心病", "气虚质", "独居老人"],
        "past_history": ["冠心病（2007年确诊）", "骨质疏松（2015年）", "白内障手术（2021年）"],
        "family_history": ["父亲：心肌梗塞", "丈夫：冠心病已去世"],
        "allergy_history": ["碘造影剂过敏"],
        "notes": "独居老人，子女均在外地。心功能较弱，活动后易气短。已设置紧急联系，需加强随访频率。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 155, "weight": 52, "waist": 78,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 6.0, "stress": "high",
        "bp_readings": [(118, 72), (122, 76), (120, 74)],
        "glucose_readings": [(4.8, "fasting")],
    },

    # ── FEMALE (女性特殊档案) ─────────────────────────────────────────────
    {
        "name": "韩素梅", "gender": "female",
        "birth_date": date(1985, 10, 12), "ethnicity": "汉族",
        "occupation": "教师",
        "id_number": "110101198510124328", "phone": "15601234001",
        "province": "北京市", "city": "北京市", "district": "东城区",
        "address": "东城区朝阳门内大街101号建国门花园3单元802",
        "emergency_contact_name": "邱明亮", "emergency_contact_phone": "15701234001",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["孕产妇", "气郁质"],
        "past_history": ["甲状腺功能减退（2020年确诊，服药中）"],
        "family_history": ["母亲：甲状腺疾病"],
        "allergy_history": ["海鲜过敏（荨麻疹）"],
        "notes": "第二胎孕期，孕28周。甲功稳定，继续监测。气郁质，情绪偶有波动，已转介心理咨询。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 162, "weight": 68, "waist": 86,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 7.5, "stress": "medium",
        "bp_readings": [(108, 68), (112, 70)],
        "glucose_readings": [(4.6, "fasting")],
    },
    {
        "name": "孔秀丽", "gender": "female",
        "birth_date": date(1990, 6, 25), "ethnicity": "汉族",
        "occupation": "设计师",
        "id_number": "310105199006254321", "phone": "15601234003",
        "province": "上海市", "city": "上海市", "district": "静安区",
        "address": "静安区新闸路1111号静安花园二期6楼",
        "emergency_contact_name": "孔建国", "emergency_contact_phone": "13801234020",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["平和质", "低风险"],
        "past_history": ["无"],
        "family_history": ["无特殊家族史"],
        "allergy_history": ["无已知过敏史"],
        "notes": "健康女性，体检未发现异常，建议每年常规体检，维持健康生活方式。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 165, "weight": 55, "waist": 72,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 8.0, "stress": "low",
        "bp_readings": [(112, 70), (110, 68)],
        "glucose_readings": [(4.8, "fasting")],
    },
    {
        "name": "江丽娟", "gender": "female",
        "birth_date": date(1978, 3, 18), "ethnicity": "汉族",
        "occupation": "会计",
        "id_number": "440106197803184523", "phone": "15601234005",
        "province": "广东省", "city": "广州市", "district": "天河区",
        "address": "天河区天河路385号太古汇旁丽思花园11楼",
        "emergency_contact_name": "傅建军", "emergency_contact_phone": "15701234003",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["高血压", "气虚质", "中风险"],
        "past_history": ["原发性高血压（2018年确诊）", "贫血（缺铁性，2015年已纠正）"],
        "family_history": ["母亲：高血压"],
        "allergy_history": ["无已知过敏史"],
        "notes": "工作压力大，长期久坐。气虚质，易乏力、头晕。血压控制尚可，需配合中医调理。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 163, "weight": 62, "waist": 83,
        "smoking": "never", "drinking": "occasional", "exercise": "occasional",
        "sleep": 6.5, "stress": "high",
        "bp_readings": [(142, 90), (138, 86), (140, 88)],
        "glucose_readings": [(5.1, "fasting")],
    },
    {
        "name": "史燕玲", "gender": "female",
        "birth_date": date(1982, 9, 7), "ethnicity": "汉族",
        "occupation": "护士",
        "id_number": "130102198209074521", "phone": "15601234007",
        "province": "河北省", "city": "石家庄市", "district": "长安区",
        "address": "长安区中华南大街389号朝阳小区4栋",
        "emergency_contact_name": "史国庆", "emergency_contact_phone": "13801234030",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["血瘀质", "中风险"],
        "past_history": ["缺铁性贫血（2019年确诊，口服补铁治疗）", "痛经（原发性，有改善）"],
        "family_history": ["母亲：贫血"],
        "allergy_history": ["对乳胶制品过敏（职业性接触性皮炎）"],
        "notes": "血瘀质，经期腹痛明显，血色偏暗有血块。已给予活血化瘀方剂，需随访疗效。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 160, "weight": 54, "waist": 74,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 7.0, "stress": "medium",
        "bp_readings": [(112, 72), (110, 70)],
        "glucose_readings": [(4.5, "fasting")],
    },
    {
        "name": "臧晓燕", "gender": "female",
        "birth_date": date(1975, 12, 30), "ethnicity": "汉族",
        "occupation": "企业主",
        "id_number": "370102197512304528", "phone": "15601234009",
        "province": "山东省", "city": "济南市", "district": "历下区",
        "address": "历下区泉城路168号泉城名邸19楼",
        "emergency_contact_name": "顾建华", "emergency_contact_phone": "15701234005",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["气郁质", "甲状腺结节"],
        "past_history": ["甲状腺结节（2019年，TI-RADS 3级，定期随访）", "抑郁症（2016年，已缓解，未用药）"],
        "family_history": ["母亲：甲状腺癌（手术后）"],
        "allergy_history": ["酒精过敏（皮肤潮红）"],
        "notes": "气郁质，情绪压抑，睡眠较差。甲状腺结节定期复查B超，上次结果稳定。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 166, "weight": 60, "waist": 79,
        "smoking": "never", "drinking": "occasional", "exercise": "occasional",
        "sleep": 5.5, "stress": "high",
        "bp_readings": [(118, 76), (120, 78)],
        "glucose_readings": [(4.9, "fasting")],
    },
    {
        "name": "骆桂英", "gender": "female",
        "birth_date": date(1968, 4, 22), "ethnicity": "汉族",
        "occupation": "退休护士长",
        "id_number": "440103196804224529", "phone": "15601234011",
        "province": "广东省", "city": "广州市", "district": "越秀区",
        "address": "越秀区东风中路99号嘉业大厦8楼",
        "emergency_contact_name": "梅国华", "emergency_contact_phone": "15501234005",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["阴虚质", "更年期"],
        "past_history": ["子宫肌瘤（2018年保守治疗）", "骨质疏松前期（2022年骨密度检查）"],
        "family_history": ["母亲：骨质疏松", "姐姐：卵巢囊肿"],
        "allergy_history": ["无已知过敏史"],
        "notes": "绝经后骨质疏松风险较高，已开始补充钙剂及维生素D。阴虚质，潮热盗汗间有发作。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 158, "weight": 58, "waist": 82,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 6.5, "stress": "medium",
        "bp_readings": [(125, 78), (122, 76)],
        "glucose_readings": [(5.0, "fasting")],
    },
    {
        "name": "倪春华", "gender": "female",
        "birth_date": date(1993, 7, 11), "ethnicity": "汉族",
        "occupation": "程序员",
        "id_number": "110106199307114521", "phone": "15601234013",
        "province": "北京市", "city": "北京市", "district": "昌平区",
        "address": "昌平区回龙观文华路188号东区18号楼",
        "emergency_contact_name": "倪建军", "emergency_contact_phone": "13801234040",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.FEMALE,
        "tags": ["痰湿质", "多囊卵巢综合征"],
        "past_history": ["多囊卵巢综合征（2020年确诊，月经不规律）", "脂肪肝（轻度，2022年B超）"],
        "family_history": ["母亲：2型糖尿病"],
        "allergy_history": ["无已知过敏史"],
        "notes": "多囊卵巢综合征，需控制体重改善胰岛素抵抗。痰湿质，建议低糖低脂饮食及有氧运动。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 163, "weight": 78, "waist": 90,
        "smoking": "never", "drinking": "occasional", "exercise": "never",
        "sleep": 7.0, "stress": "high",
        "bp_readings": [(118, 75), (120, 76)],
        "glucose_readings": [(5.8, "fasting"), (8.2, "postmeal_2h")],
    },

    # ── CHILD (0-6岁儿童) ────────────────────────────────────────────────
    {
        "name": "方小明", "gender": "male",
        "birth_date": date(2022, 6, 1), "ethnicity": "汉族",
        "occupation": "",
        "id_type": IdType.BIRTH_CERT,
        "id_number": "BC20220601001", "phone": "15701234001",  # 监护人电话
        "province": "北京市", "city": "北京市", "district": "东城区",
        "address": "东城区朝阳门内大街101号建国门花园3单元802",
        "emergency_contact_name": "邱明亮", "emergency_contact_phone": "15701234001",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.CHILD,
        "tags": ["儿童保健"],
        "past_history": ["新生儿黄疸（已自愈）", "手足口病（2023年7月）"],
        "family_history": ["父亲：无", "母亲：甲减"],
        "allergy_history": ["对芒果过敏（口腔周围皮疹）"],
        "notes": "第二个孩子，生长发育正常。已完成月龄内所有预防接种。定期儿保。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 88, "weight": 12.5, "waist": 49,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 11.0, "stress": "low",
        "bp_readings": [],
        "glucose_readings": [],
    },
    {
        "name": "庄晨曦", "gender": "female",
        "birth_date": date(2021, 3, 15), "ethnicity": "汉族",
        "occupation": "",
        "id_type": IdType.BIRTH_CERT,
        "id_number": "BC20210315002", "phone": "15701234007",  # 监护人
        "province": "山东省", "city": "济南市", "district": "历下区",
        "address": "历下区泉城路168号泉城名邸19楼",
        "emergency_contact_name": "顾建华", "emergency_contact_phone": "15701234005",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.CHILD,
        "tags": ["儿童保健"],
        "past_history": ["反复上呼吸道感染（年均4-5次）"],
        "family_history": ["父亲：无", "母亲：气郁质"],
        "allergy_history": ["无已知过敏史"],
        "notes": "反复呼吸道感染，中医辨证为肺脾气虚，已给予玉屏风颗粒，效果待观察。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 95, "weight": 14, "waist": 51,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 10.5, "stress": "low",
        "bp_readings": [],
        "glucose_readings": [],
    },
    {
        "name": "钱浩然", "gender": "male",
        "birth_date": date(2020, 8, 20), "ethnicity": "汉族",
        "occupation": "",
        "id_type": IdType.BIRTH_CERT,
        "id_number": "BC20200820003", "phone": "15701234009",
        "province": "河北省", "city": "石家庄市", "district": "长安区",
        "address": "长安区中华南大街389号朝阳小区4栋",
        "emergency_contact_name": "史燕玲", "emergency_contact_phone": "15601234007",
        "emergency_contact_relation": "母亲",
        "archive_type": ArchiveType.CHILD,
        "tags": ["儿童保健", "特禀质"],
        "past_history": ["湿疹（婴儿期，已好转）", "过敏性鼻炎（2022年）"],
        "family_history": ["母亲：过敏体质"],
        "allergy_history": ["鸡蛋过敏（荨麻疹）", "尘螨过敏"],
        "notes": "特禀质，过敏体质明显。避免接触过敏原，家中使用防螨床品。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 100, "weight": 16, "waist": 53,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 10.0, "stress": "low",
        "bp_readings": [],
        "glucose_readings": [],
    },
    {
        "name": "孙欣雨", "gender": "female",
        "birth_date": date(2023, 1, 10), "ethnicity": "汉族",
        "occupation": "",
        "id_type": IdType.BIRTH_CERT,
        "id_number": "BC20230110004", "phone": "15701234011",
        "province": "广东省", "city": "广州市", "district": "天河区",
        "address": "天河区天河路385号太古汇旁丽思花园11楼",
        "emergency_contact_name": "傅建军", "emergency_contact_phone": "15701234003",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.CHILD,
        "tags": ["儿童保健"],
        "past_history": ["无"],
        "family_history": ["健康"],
        "allergy_history": ["无已知过敏史"],
        "notes": "新生儿建档，生长发育正常，母乳喂养。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 72, "weight": 7.8, "waist": 42,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 14.0, "stress": "low",
        "bp_readings": [],
        "glucose_readings": [],
    },
    {
        "name": "朱书涵", "gender": "male",
        "birth_date": date(2019, 11, 25), "ethnicity": "汉族",
        "occupation": "",
        "id_type": IdType.BIRTH_CERT,
        "id_number": "BC20191125005", "phone": "15701234013",
        "province": "浙江省", "city": "杭州市", "district": "西湖区",
        "address": "西湖区文三路478号西子花园小区B幢",
        "emergency_contact_name": "项国强", "emergency_contact_phone": "15501234013",
        "emergency_contact_relation": "祖父",
        "archive_type": ArchiveType.CHILD,
        "tags": ["儿童保健", "超重"],
        "past_history": ["腺样体肥大（2023年，保守治疗）", "龋齿治疗（2024年）"],
        "family_history": ["祖父：糖尿病", "父亲：高血脂"],
        "allergy_history": ["无已知过敏史"],
        "notes": "体重偏重，BMI超出正常范围。祖父有糖尿病史，需注意饮食控制，减少甜食和零食摄入。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 115, "weight": 26, "waist": 62,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 9.5, "stress": "low",
        "bp_readings": [],
        "glucose_readings": [],
    },

    # ── KEY_FOCUS (重点关注人群) ──────────────────────────────────────────
    {
        "name": "许振海", "gender": "male",
        "birth_date": date(1970, 5, 14), "ethnicity": "汉族",
        "occupation": "个体商户",
        "id_number": "110102197005143519", "phone": "15701234015",
        "province": "北京市", "city": "北京市", "district": "丰台区",
        "address": "丰台区丰台路168号丽景花园A区8栋3单元",
        "emergency_contact_name": "许建华", "emergency_contact_phone": "13801234050",
        "emergency_contact_relation": "兄弟",
        "archive_type": ArchiveType.KEY_FOCUS,
        "tags": ["高血压", "糖尿病", "冠心病", "血瘀质", "高风险"],
        "past_history": ["原发性高血压（2005年确诊）", "2型糖尿病（2008年确诊）", "冠心病（2018年确诊，支架手术2根）", "高脂血症"],
        "family_history": ["父亲：心肌梗塞（58岁去世）", "母亲：高血压、糖尿病", "兄弟：高血压"],
        "allergy_history": ["磺脲类降糖药过敏（低血糖严重）"],
        "notes": "三病共存，心血管风险极高。需严格控制血压、血糖，每月必须复诊。吸烟史已戒除。重点监控对象。",
        "has_hypertension": True, "has_diabetes": True,
        "height": 173, "weight": 88, "waist": 102,
        "smoking": "former", "drinking": "former", "exercise": "occasional",
        "sleep": 6.0, "stress": "high",
        "bp_readings": [(165, 102), (158, 96), (155, 94), (152, 92)],
        "glucose_readings": [(10.2, "fasting"), (14.8, "postmeal_2h"), (9.8, "fasting")],
    },
    {
        "name": "傅建军", "gender": "male",
        "birth_date": date(1965, 9, 28), "ethnicity": "汉族",
        "occupation": "公司经理",
        "id_number": "440102196509283518", "phone": "15701234003",
        "province": "广东省", "city": "广州市", "district": "天河区",
        "address": "天河区天河路385号太古汇旁丽思花园11楼",
        "emergency_contact_name": "江丽娟", "emergency_contact_phone": "15601234005",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.KEY_FOCUS,
        "tags": ["脑卒中", "高血压", "阳虚质", "高风险"],
        "past_history": ["脑卒中（2021年9月，右侧大脑中动脉梗塞）", "原发性高血压（2010年确诊）", "颈动脉斑块"],
        "family_history": ["父亲：高血压、脑卒中", "母亲：高血压"],
        "allergy_history": ["无已知过敏史"],
        "notes": "脑卒中后康复期，右侧肢体功能基本恢复，言语略有障碍。血压控制是防止复发关键，目标<130/80。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 175, "weight": 80, "waist": 95,
        "smoking": "former", "drinking": "never", "exercise": "occasional",
        "sleep": 7.5, "stress": "medium",
        "bp_readings": [(152, 94), (148, 90), (145, 88)],
        "glucose_readings": [(5.5, "fasting")],
    },
    {
        "name": "曾美华", "gender": "female",
        "birth_date": date(1968, 7, 3), "ethnicity": "汉族",
        "occupation": "会计",
        "id_number": "430102196807034523", "phone": "15701234017",
        "province": "湖南省", "city": "长沙市", "district": "岳麓区",
        "address": "岳麓区桐梓坡路88号融科君域8栋",
        "emergency_contact_name": "曾建国", "emergency_contact_phone": "13801234060",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.KEY_FOCUS,
        "tags": ["糖尿病", "慢性肾病", "痰湿质", "高风险"],
        "past_history": ["2型糖尿病（2005年确诊）", "糖尿病肾病（2019年，GFR 55ml/min）", "高脂血症"],
        "family_history": ["母亲：2型糖尿病", "兄弟：肾病"],
        "allergy_history": ["对比剂过敏（过敏史记录）"],
        "notes": "糖尿病肾病3期，需严格控制蛋白质摄入，监测肾功能。每季度检测肌酐、尿微量蛋白。",
        "has_hypertension": False, "has_diabetes": True,
        "height": 160, "weight": 74, "waist": 92,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 7.0, "stress": "medium",
        "bp_readings": [(128, 82), (132, 84)],
        "glucose_readings": [(11.5, "fasting"), (15.2, "postmeal_2h"), (10.8, "fasting")],
    },
    {
        "name": "彭国林", "gender": "male",
        "birth_date": date(1958, 1, 16), "ethnicity": "汉族",
        "occupation": "退休矿工",
        "id_number": "420102195801163518", "phone": "15701234019",
        "province": "湖北省", "city": "武汉市", "district": "洪山区",
        "address": "洪山区珞喻路187号民大院3栋",
        "emergency_contact_name": "彭晓华", "emergency_contact_phone": "13801234070",
        "emergency_contact_relation": "子女",
        "archive_type": ArchiveType.KEY_FOCUS,
        "tags": ["慢阻肺", "高血压", "气虚质", "高风险"],
        "past_history": ["慢性阻塞性肺疾病III期（职业尘肺，2010年确诊）", "原发性高血压（2008年确诊）", "肺心病（2020年）"],
        "family_history": ["父亲：肺病（矿工）"],
        "allergy_history": ["无已知过敏史"],
        "notes": "重度慢阻肺，长期家庭氧疗。活动耐力极差，上楼梯即气喘。需避免呼吸道感染，已接种肺炎疫苗。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 168, "weight": 55, "waist": 78,
        "smoking": "former", "drinking": "never", "exercise": "never",
        "sleep": 7.0, "stress": "medium",
        "bp_readings": [(148, 90), (145, 88)],
        "glucose_readings": [(5.3, "fasting")],
    },
    {
        "name": "廖建萍", "gender": "female",
        "birth_date": date(1972, 11, 22), "ethnicity": "汉族",
        "occupation": "个体经营",
        "id_number": "440102197211224523", "phone": "15701234021",
        "province": "广东省", "city": "广州市", "district": "越秀区",
        "address": "越秀区中山六路89号康苑小区11层",
        "emergency_contact_name": "尤永辉", "emergency_contact_phone": "15701234023",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.KEY_FOCUS,
        "tags": ["高血压", "冠心病", "血瘀质", "高风险"],
        "past_history": ["原发性高血压（2007年确诊）", "冠心病（2019年，心绞痛，保守治疗）", "高脂血症"],
        "family_history": ["父亲：冠心病", "母亲：高血压"],
        "allergy_history": ["他汀类药物肌痛（已换药）"],
        "notes": "冠心病心绞痛，活动后偶有发作。已调整降脂方案，血压控制尚可。血瘀质，中医治以活血化瘀。",
        "has_hypertension": True, "has_diabetes": False,
        "height": 162, "weight": 68, "waist": 88,
        "smoking": "never", "drinking": "never", "exercise": "occasional",
        "sleep": 6.5, "stress": "high",
        "bp_readings": [(148, 92), (145, 88), (142, 86)],
        "glucose_readings": [(5.4, "fasting")],
    },

    # ── NORMAL (普通居民) ─────────────────────────────────────────────────
    {
        "name": "邱明亮", "gender": "male",
        "birth_date": date(1988, 4, 5), "ethnicity": "汉族",
        "occupation": "工程师",
        "id_number": "110101198804053519", "phone": "15701234001",
        "province": "北京市", "city": "北京市", "district": "东城区",
        "address": "东城区朝阳门内大街101号建国门花园3单元802",
        "emergency_contact_name": "韩素梅", "emergency_contact_phone": "15601234001",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.NORMAL,
        "tags": ["平和质", "低风险"],
        "past_history": ["阑尾炎手术（2010年）"],
        "family_history": ["父亲：高血压（轻度）"],
        "allergy_history": ["无已知过敏史"],
        "notes": "健康体检，无慢性病。平和质，建议定期体检，维持健康生活方式。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 178, "weight": 75, "waist": 85,
        "smoking": "never", "drinking": "occasional", "exercise": "regular",
        "sleep": 7.5, "stress": "medium",
        "bp_readings": [(118, 76), (120, 78)],
        "glucose_readings": [(5.0, "fasting")],
    },
    {
        "name": "潘雪梅", "gender": "female",
        "birth_date": date(1992, 8, 19), "ethnicity": "汉族",
        "occupation": "市场营销",
        "id_number": "110105199208194322", "phone": "15701234025",
        "province": "北京市", "city": "北京市", "district": "昌平区",
        "address": "昌平区天通苑北区5区23号楼",
        "emergency_contact_name": "潘建国", "emergency_contact_phone": "13801234080",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.NORMAL,
        "tags": ["气郁质", "亚健康"],
        "past_history": ["慢性咽炎（2018年）"],
        "family_history": ["无特殊家族史"],
        "allergy_history": ["对花粉轻度过敏"],
        "notes": "气郁质，情绪压抑，睡眠质量差。近期工作压力较大，偶有心悸、胸闷。建议心理疏导及中医调理。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 163, "weight": 56, "waist": 74,
        "smoking": "never", "drinking": "occasional", "exercise": "never",
        "sleep": 5.0, "stress": "high",
        "bp_readings": [(110, 70), (112, 72)],
        "glucose_readings": [(4.7, "fasting")],
    },
    {
        "name": "顾建华", "gender": "male",
        "birth_date": date(1983, 12, 7), "ethnicity": "汉族",
        "occupation": "律师",
        "id_number": "370102198312073519", "phone": "15701234005",
        "province": "山东省", "city": "济南市", "district": "历下区",
        "address": "历下区泉城路168号泉城名邸19楼",
        "emergency_contact_name": "臧晓燕", "emergency_contact_phone": "15601234009",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.NORMAL,
        "tags": ["气虚质", "高血压初期"],
        "past_history": ["高血压前期（2023年体检，血压135/85，随访观察）"],
        "family_history": ["父亲：高血压", "母亲：冠心病"],
        "allergy_history": ["无已知过敏史"],
        "notes": "血压偏高（高血压前期），暂不用药，调整生活方式。需减少钠盐摄入，加强有氧运动。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 180, "weight": 85, "waist": 96,
        "smoking": "occasional", "drinking": "regular", "exercise": "occasional",
        "sleep": 6.5, "stress": "high",
        "bp_readings": [(135, 85), (138, 88), (132, 84)],
        "glucose_readings": [(5.2, "fasting")],
    },
    {
        "name": "薛文静", "gender": "female",
        "birth_date": date(1996, 2, 14), "ethnicity": "汉族",
        "occupation": "大学生",
        "id_number": "110102199602144522", "phone": "15701234027",
        "province": "北京市", "city": "北京市", "district": "海淀区",
        "address": "海淀区学院路37号北京大学附近家属区",
        "emergency_contact_name": "薛国华", "emergency_contact_phone": "13801234090",
        "emergency_contact_relation": "父亲",
        "archive_type": ArchiveType.NORMAL,
        "tags": ["平和质", "低风险"],
        "past_history": ["无"],
        "family_history": ["无特殊家族史"],
        "allergy_history": ["无已知过敏史"],
        "notes": "在校大学生，健康状况良好。建议保持规律作息，注意营养均衡。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 165, "weight": 52, "waist": 68,
        "smoking": "never", "drinking": "never", "exercise": "regular",
        "sleep": 8.5, "stress": "low",
        "bp_readings": [(108, 66), (110, 68)],
        "glucose_readings": [(4.5, "fasting")],
    },
    {
        "name": "尤永辉", "gender": "male",
        "birth_date": date(1975, 6, 30), "ethnicity": "汉族",
        "occupation": "商人",
        "id_number": "440102197506303519", "phone": "15701234023",
        "province": "广东省", "city": "广州市", "district": "越秀区",
        "address": "越秀区中山六路89号康苑小区11层",
        "emergency_contact_name": "廖建萍", "emergency_contact_phone": "15701234021",
        "emergency_contact_relation": "配偶",
        "archive_type": ArchiveType.NORMAL,
        "tags": ["痰湿质", "脂肪肝"],
        "past_history": ["脂肪肝（中度，2021年B超）", "高脂血症（2021年确诊）"],
        "family_history": ["父亲：高血压、冠心病"],
        "allergy_history": ["无已知过敏史"],
        "notes": "长期应酬饮食，体重超重，脂肪肝中度。已建议戒酒、减重。痰湿质需化湿降脂，中医调理进行中。",
        "has_hypertension": False, "has_diabetes": False,
        "height": 175, "weight": 95, "waist": 108,
        "smoking": "current", "drinking": "regular", "exercise": "never",
        "sleep": 7.0, "stress": "medium",
        "bp_readings": [(132, 84), (135, 86)],
        "glucose_readings": [(5.6, "fasting"), (7.8, "postmeal_2h")],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 家庭档案（按电话匹配）
# ─────────────────────────────────────────────────────────────────────────────

FAMILIES = [
    {
        "name": "吴振国·卫秀英家庭",
        "address": "北京市朝阳区劲松路27号院3单元502室",
        "notes": "老年双职工家庭，两人均有慢病管理需求",
        "head_phone": "15501234001",
        "members": [
            {"phone": "15501234001", "relation": "户主"},
            {"phone": "15501234011", "relation": "配偶"},
        ]
    },
    {
        "name": "梅国华·骆桂英家庭",
        "address": "广东省广州市越秀区东风中路99号嘉业大厦8楼",
        "notes": "双退休老年家庭，心血管风险需重点管理",
        "head_phone": "15501234005",
        "members": [
            {"phone": "15501234005", "relation": "户主"},
            {"phone": "15601234011", "relation": "配偶"},
        ]
    },
    {
        "name": "褚永年·龚桂芳家庭",
        "address": "江苏省南京市鼓楼区中山路256号天华大厦3楼302",
        "notes": "脑卒中后遗症与糖尿病慢阻肺双慢病老年家庭",
        "head_phone": "15501234009",
        "members": [
            {"phone": "15501234009", "relation": "户主"},
            {"phone": "15501234007", "relation": "配偶"},
        ]
    },
    {
        "name": "邱明亮·韩素梅·方小明家庭",
        "address": "北京市东城区朝阳门内大街101号建国门花园3单元802",
        "notes": "小两口带幼儿，孕产妇及儿童保健档案",
        "head_phone": "15701234001",
        "members": [
            {"phone": "15701234001", "relation": "户主"},
            {"phone": "15601234001", "relation": "配偶"},
            {"phone": "15701234001", "relation": "子女"},  # 方小明监护人同号，用另一个标识
        ]
    },
    {
        "name": "傅建军·江丽娟·孙欣雨家庭",
        "address": "广东省广州市天河区天河路385号太古汇旁丽思花园11楼",
        "notes": "脑卒中丈夫与高血压妻子，新生儿家庭",
        "head_phone": "15701234003",
        "members": [
            {"phone": "15701234003", "relation": "户主"},
            {"phone": "15601234005", "relation": "配偶"},
        ]
    },
    {
        "name": "顾建华·臧晓燕·庄晨曦家庭",
        "address": "山东省济南市历下区泉城路168号泉城名邸19楼",
        "notes": "双职工家庭，女儿反复呼吸道感染",
        "head_phone": "15701234005",
        "members": [
            {"phone": "15701234005", "relation": "户主"},
            {"phone": "15601234009", "relation": "配偶"},
        ]
    },
    {
        "name": "尤永辉·廖建萍家庭",
        "address": "广东省广州市越秀区中山六路89号康苑小区11层",
        "notes": "双慢病高风险家庭，需共同管理心血管风险",
        "head_phone": "15701234023",
        "members": [
            {"phone": "15701234023", "relation": "户主"},
            {"phone": "15701234021", "relation": "配偶"},
        ]
    },
    {
        "name": "许振海家庭",
        "address": "北京市丰台区丰台路168号丽景花园A区8栋3单元",
        "notes": "三病共存高危家庭，需重点管理",
        "head_phone": "15701234015",
        "members": [
            {"phone": "15701234015", "relation": "户主"},
        ]
    },
]

# 标签 ID 映射（对应 seed_labels.py 中的标签）
LABEL_MAP = {
    "高血压": 1, "糖尿病": 2, "冠心病": 3, "脑卒中": 4, "慢阻肺": 5,
    "平和质": 6, "气虚质": 7, "阳虚质": 8, "阴虚质": 9, "痰湿质": 10,
    "湿热质": 11, "血瘀质": 12, "气郁质": 13, "特禀质": 14,
    "高风险": 15, "中风险": 16, "低风险": 17,
    "规律随访": 18, "偶尔随访": 19, "失访": 20,
    "孕产妇": 21, "残疾人": 22, "低保户": 23, "独居老人": 24,
}

# 不在 LABEL_MAP 里的标签（自定义）
CUSTOM_LABEL_NAMES = [
    "儿童保健", "亚健康", "更年期", "甲状腺结节", "多囊卵巢综合征",
    "超重", "脂肪肝", "慢性肾病", "儿童保健", "特禀质",
]


async def ensure_labels(sess: AsyncSession) -> dict:
    """确保标签分类和标签存在，返回 name->id 映射"""
    name_to_id = {}

    # 系统标签
    for name, lid in LABEL_MAP.items():
        lbl = await sess.get(Label, lid)
        if lbl:
            name_to_id[name] = lid

    # 自定义标签（category_id=None，scope=CUSTOM）
    for name in CUSTOM_LABEL_NAMES:
        if name in name_to_id:
            continue
        r = await sess.execute(select(Label).where(Label.name == name))
        lbl = r.scalars().first()
        if not lbl:
            lbl = Label(name=name, scope="CUSTOM", color="#6b7280", is_active=True)
            sess.add(lbl)
            await sess.flush()
        name_to_id[name] = lbl.id

    return name_to_id


async def seed_patients(sess: AsyncSession) -> dict:
    """新增患者档案，返回 phone->archive 映射"""
    phone_to_archive = {}

    for p in PATIENTS:
        phone = p["phone"]
        # 幂等：已存在则跳过
        r = await sess.execute(
            select(PatientArchive).where(PatientArchive.phone == phone)
        )
        existing = r.scalars().first()
        if existing:
            phone_to_archive[phone] = existing
            continue

        archive = PatientArchive(
            id=uuid.uuid4(),
            user_id=None,
            name=p["name"],
            gender=p["gender"],
            birth_date=p["birth_date"],
            ethnicity=p.get("ethnicity", "汉族"),
            occupation=p.get("occupation", ""),
            id_type=p.get("id_type", IdType.ID_CARD),
            id_number=p.get("id_number"),
            phone=phone,
            phone2=p.get("phone2"),
            email=p.get("email"),
            province=p.get("province"),
            city=p.get("city"),
            district=p.get("district"),
            address=p.get("address"),
            emergency_contact_name=p.get("emergency_contact_name"),
            emergency_contact_phone=p.get("emergency_contact_phone"),
            emergency_contact_relation=p.get("emergency_contact_relation"),
            archive_type=p["archive_type"],
            tags=p.get("tags", []),
            past_history=p.get("past_history", []),
            family_history=p.get("family_history", []),
            allergy_history=p.get("allergy_history", []),
            notes=p.get("notes"),
            is_deleted=False,
        )
        sess.add(archive)
        phone_to_archive[phone] = archive

    await sess.flush()
    return phone_to_archive


async def seed_health_profiles(sess: AsyncSession, phone_to_archive: dict):
    """为每个患者新增健康档案"""
    for p in PATIENTS:
        archive = phone_to_archive.get(p["phone"])
        if not archive or not archive.user_id:
            # HealthProfile 绑定 user_id，如无 user 则跳过
            continue

        r = await sess.execute(
            select(HealthProfile).where(HealthProfile.user_id == archive.user_id)
        )
        if r.scalars().first():
            continue

        hp = HealthProfile(
            id=uuid.uuid4(),
            user_id=archive.user_id,
            gender=p["gender"],
            birth_date=p["birth_date"],
            height_cm=float(p.get("height", 165)),
            weight_kg=float(p.get("weight", 60)),
            waist_cm=float(p.get("waist", 80)),
            past_history={"list": p.get("past_history", [])},
            family_history={"list": p.get("family_history", [])},
            allergy_history={"list": p.get("allergy_history", [])},
            smoking=p.get("smoking", "never"),
            drinking=p.get("drinking", "never"),
            exercise_frequency=p.get("exercise", "occasional"),
            sleep_hours=float(p.get("sleep", 7.0)),
            stress_level=p.get("stress", "low"),
        )
        sess.add(hp)


async def seed_indicators(sess: AsyncSession, phone_to_archive: dict):
    """为有慢病的患者新增健康指标记录"""
    from datetime import timezone as tz
    now = datetime.now(tz.utc)

    for p in PATIENTS:
        archive = phone_to_archive.get(p["phone"])
        if not archive or not archive.user_id:
            continue

        # 检查是否已有指标
        r = await sess.execute(
            select(func.count()).select_from(HealthIndicator).where(
                HealthIndicator.user_id == archive.user_id
            )
        )
        if (r.scalar() or 0) > 0:
            continue

        base_time = now - timedelta(days=60)

        # 血压
        for i, (sys, dia) in enumerate(p.get("bp_readings", [])):
            sess.add(HealthIndicator(
                id=uuid.uuid4(),
                user_id=archive.user_id,
                indicator_type=IndicatorType.BLOOD_PRESSURE,
                values={"systolic": sys, "diastolic": dia},
                scene="morning",
                recorded_at=base_time + timedelta(days=i * 15),
            ))

        # 血糖
        for i, (val, scene) in enumerate(p.get("glucose_readings", [])):
            sess.add(HealthIndicator(
                id=uuid.uuid4(),
                user_id=archive.user_id,
                indicator_type=IndicatorType.BLOOD_GLUCOSE,
                values={"value": val},
                scene=scene,
                recorded_at=base_time + timedelta(days=i * 10),
            ))

        # 体重
        weight = p.get("weight")
        if weight:
            sess.add(HealthIndicator(
                id=uuid.uuid4(),
                user_id=archive.user_id,
                indicator_type=IndicatorType.WEIGHT,
                values={"value": float(weight)},
                recorded_at=base_time,
            ))


async def seed_chronic_diseases(sess: AsyncSession, phone_to_archive: dict):
    """新增慢性病记录"""
    for p in PATIENTS:
        archive = phone_to_archive.get(p["phone"])
        if not archive or not archive.user_id:
            continue

        if p.get("has_hypertension"):
            r = await sess.execute(
                select(ChronicDiseaseRecord).where(
                    ChronicDiseaseRecord.user_id == archive.user_id,
                    ChronicDiseaseRecord.disease_type == DiseaseType.HYPERTENSION
                )
            )
            if not r.scalars().first():
                sess.add(ChronicDiseaseRecord(
                    id=uuid.uuid4(),
                    user_id=archive.user_id,
                    disease_type=DiseaseType.HYPERTENSION,
                    diagnosed_at=date(2008, 1, 1),
                    diagnosed_hospital="社区卫生服务中心",
                    medications=[
                        {"name": "苯磺酸氨氯地平", "dose": "5mg", "frequency": "每日1次"},
                        {"name": "厄贝沙坦", "dose": "150mg", "frequency": "每日1次"},
                    ],
                    target_values={"systolic_target": 130, "diastolic_target": 80},
                    notes="原发性高血压，长期口服降压药，控制达标",
                    is_active=True,
                ))

        if p.get("has_diabetes"):
            r = await sess.execute(
                select(ChronicDiseaseRecord).where(
                    ChronicDiseaseRecord.user_id == archive.user_id,
                    ChronicDiseaseRecord.disease_type == DiseaseType.DIABETES_T2
                )
            )
            if not r.scalars().first():
                sess.add(ChronicDiseaseRecord(
                    id=uuid.uuid4(),
                    user_id=archive.user_id,
                    disease_type=DiseaseType.DIABETES_T2,
                    diagnosed_at=date(2013, 1, 1),
                    diagnosed_hospital="社区卫生服务中心",
                    medications=[
                        {"name": "二甲双胍", "dose": "500mg", "frequency": "每日3次，随餐"},
                    ],
                    target_values={"hba1c_target": 7.0},
                    notes="2型糖尿病，口服降糖药控制",
                    is_active=True,
                ))


async def seed_patient_labels(
    sess: AsyncSession, phone_to_archive: dict, label_name_to_id: dict
):
    """为患者打标签"""
    for p in PATIENTS:
        archive = phone_to_archive.get(p["phone"])
        if not archive:
            continue

        for tag_name in p.get("tags", []):
            lid = label_name_to_id.get(tag_name)
            if not lid:
                continue
            # 检查是否已有
            r = await sess.execute(
                select(PatientLabel).where(
                    PatientLabel.patient_id == archive.id,
                    PatientLabel.label_id == lid,
                )
            )
            if not r.scalars().first():
                sess.add(PatientLabel(
                    patient_id=archive.id,
                    label_id=lid,
                ))


async def seed_family_archives(sess: AsyncSession, phone_to_archive: dict):
    """新增家庭档案及成员关系"""
    for fam in FAMILIES:
        # 幂等：按家庭名去重
        r = await sess.execute(
            select(FamilyArchive).where(FamilyArchive.family_name == fam["name"])
        )
        existing_fam = r.scalars().first()
        if existing_fam:
            continue

        head = phone_to_archive.get(fam["head_phone"])
        family = FamilyArchive(
            id=uuid.uuid4(),
            family_name=fam["name"],
            address=fam.get("address", ""),
            head_archive_id=head.id if head else None,
            member_count=len(fam["members"]),
            notes=fam.get("notes"),
        )
        sess.add(family)
        await sess.flush()

        for m in fam["members"]:
            archive = phone_to_archive.get(m["phone"])
            if not archive:
                continue
            # 检查成员关系是否已存在
            r2 = await sess.execute(
                select(ArchiveFamilyMember).where(
                    ArchiveFamilyMember.family_id == family.id,
                    ArchiveFamilyMember.archive_id == archive.id,
                )
            )
            if not r2.scalars().first():
                sess.add(ArchiveFamilyMember(
                    id=uuid.uuid4(),
                    family_id=family.id,
                    archive_id=archive.id,
                    relation=m["relation"],
                ))


async def main():
    print("=== 50患者全量数据 Seed ===")

    async with AsyncSessionLocal() as sess:
        # 1. 确保标签存在
        print("[1/5] 确保标签数据...")
        label_name_to_id = await ensure_labels(sess)
        await sess.commit()

        # 2. 新增患者档案
        print("[2/5] 新增患者档案...")
        phone_to_archive = await seed_patients(sess)
        await sess.commit()

        # 统计
        added = sum(1 for p in PATIENTS if p["phone"] in phone_to_archive
                    and phone_to_archive[p["phone"]].name == p["name"])
        print(f"    患者档案：新增/已有 {len(phone_to_archive)} 条")

        # 3. 健康档案（仅对有 user_id 的患者）
        print("[3/5] 新增健康档案及指标...")
        await seed_health_profiles(sess, phone_to_archive)
        await seed_indicators(sess, phone_to_archive)
        await seed_chronic_diseases(sess, phone_to_archive)
        await sess.commit()

        # 4. 患者标签
        print("[4/5] 设置患者标签...")
        await seed_patient_labels(sess, phone_to_archive, label_name_to_id)
        await sess.commit()

        # 5. 家庭档案
        print("[5/5] 新增家庭档案...")
        await seed_family_archives(sess, phone_to_archive)
        await sess.commit()

    # 统计结果
    async with AsyncSessionLocal() as sess:
        total_archives = await sess.scalar(
            select(func.count()).select_from(PatientArchive).where(
                PatientArchive.is_deleted == False
            )
        )
        total_families = await sess.scalar(
            select(func.count()).select_from(FamilyArchive)
        )
        total_labels = await sess.scalar(
            select(func.count()).select_from(PatientLabel)
        )
        print(f"\n=== 完成 ===")
        print(f"    患者档案总数: {total_archives}")
        print(f"    家庭档案总数: {total_families}")
        print(f"    患者标签总数: {total_labels}")


if __name__ == "__main__":
    asyncio.run(main())
