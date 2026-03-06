"""
丰富演示数据 Seed 脚本 —— 造出 25 位真实感患者。

运行方式：
    python scripts/seed_rich_demo.py

注意：先运行 seed_demo.py（或启动服务让其自动跑），确保基础数据（体质问卷/规则/模板）已存在。
本脚本仅新增患者及其关联数据，幂等（按 phone 去重）。
"""
import asyncio
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, Base, engine
from app.models.alert import AlertEvent, AlertRule
from app.models.constitution import (
    ConstitutionAnswer,
    ConstitutionAssessment,
    ConstitutionQuestion,
)
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AssessmentStatus,
    BodyType,
    CheckInStatus,
    DiseaseType,
    FollowupStatus,
    IndicatorType,
    TaskType,
    UserRole,
)
from app.models.archive import PatientArchive, FamilyArchive, ArchiveFamilyMember
from app.models.clinical import ClinicalDocument
from app.models.scale import Scale, ScaleRecord
from app.models.enums import ArchiveType, IdType
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile
from app.models.user import User
from app.services.auth_service import hash_password

# ── 档案生成辅助 ──
_PHONE_PREFIXES = ["138", "139", "150", "151", "152", "158", "159", "186", "187", "188", "177", "176"]
_DISTRICTS = ["朝阳区", "海淀区", "西城区", "东城区", "丰台区", "昌平区", "顺义区", "通州区"]
_CITIES = [
    ("北京市", "北京市"), ("上海市", "上海市"), ("广东省", "广州市"),
    ("浙江省", "杭州市"), ("湖北省", "武汉市"), ("四川省", "成都市"),
]
_OCCUPATIONS = ["退休工人", "工程师", "教师", "农民", "工人", "自由职业", "企业职员", "公务员", "退休教师", "退休干部"]


def _gen_phone(seed_str: str) -> str:
    h = abs(hash(seed_str))
    prefix = _PHONE_PREFIXES[h % len(_PHONE_PREFIXES)]
    return prefix + str(h % 100_000_000).zfill(8)


def _gen_id_number(birth_year: int, birth_month: int, birth_day: int, gender: str, seed: int) -> str:
    regions = ["110101", "310101", "440101", "330101", "420101", "510101"]
    region = regions[seed % len(regions)]
    bdate = f"{birth_year:04d}{birth_month:02d}{birth_day:02d}"
    base_seq = 100 + (seed % 899)
    seq = base_seq | 1 if gender == "male" else (base_seq // 2) * 2
    return f"{region}{bdate}{seq:03d}X"

# ── 随机种子，保证每次生成相同数据 ──
random.seed(42)

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


# ════════════════════════════════════════════════════════
# 患者基础信息定义（25人）
# ════════════════════════════════════════════════════════

PATIENTS = [
    # 高血压患者（10人）
    {
        "phone": "p_zhang_wei",
        "name": "张伟",
        "gender": "male",
        "birth_year": 1958,
        "height": 172,
        "weight": 78,
        "waist": 92,
        "smoking": "former",
        "drinking": "occasional",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "hospital": "北京协和医院",
        "dx_year": 2015,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "氨氯地平", "dose": "5mg", "frequency": "每日一次", "start_date": "2015-03-10"},
                {"name": "厄贝沙坦", "dose": "150mg", "frequency": "每日一次", "start_date": "2018-06-01"},
            ]
        },
        "bp_base": (148, 92),
        "bp_sigma": (12, 8),
    },
    {
        "phone": "p_li_fang",
        "name": "李芳",
        "gender": "female",
        "birth_year": 1963,
        "height": 158,
        "weight": 65,
        "waist": 84,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.0,
        "stress": "low",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.YIN_DEFICIENCY,
        "hospital": "上海华山医院",
        "dx_year": 2018,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "苯磺酸氨氯地平", "dose": "5mg", "frequency": "每日一次", "start_date": "2018-09-15"},
            ]
        },
        "bp_base": (138, 86),
        "bp_sigma": (10, 6),
    },
    {
        "phone": "p_wang_guohua",
        "name": "王国华",
        "gender": "male",
        "birth_year": 1952,
        "height": 168,
        "weight": 82,
        "waist": 98,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.5,
        "stress": "high",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.BLOOD_STASIS,
        "hospital": "广州中山医院",
        "dx_year": 2010,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "硝苯地平控释片", "dose": "30mg", "frequency": "每日一次", "start_date": "2010-05-20"},
                {"name": "卡托普利", "dose": "25mg", "frequency": "每日两次", "start_date": "2012-01-08"},
            ]
        },
        "bp_base": (162, 100),
        "bp_sigma": (15, 10),
    },
    {
        "phone": "p_chen_xiuying",
        "name": "陈秀英",
        "gender": "female",
        "birth_year": 1955,
        "height": 155,
        "weight": 60,
        "waist": 80,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.5,
        "stress": "low",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.QI_DEFICIENCY,
        "hospital": "成都华西医院",
        "dx_year": 2017,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "培哚普利", "dose": "4mg", "frequency": "每日一次", "start_date": "2017-04-12"},
            ]
        },
        "bp_base": (135, 84),
        "bp_sigma": (8, 5),
    },
    {
        "phone": "p_zhao_junmin",
        "name": "赵俊民",
        "gender": "male",
        "birth_year": 1960,
        "height": 175,
        "weight": 88,
        "waist": 100,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 6.0,
        "stress": "high",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.DAMP_HEAT,
        "hospital": "武汉同济医院",
        "dx_year": 2013,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "美托洛尔", "dose": "50mg", "frequency": "每日两次", "start_date": "2013-11-05"},
                {"name": "氢氯噻嗪", "dose": "12.5mg", "frequency": "每日一次", "start_date": "2015-03-20"},
            ]
        },
        "bp_base": (155, 96),
        "bp_sigma": (18, 12),
    },
    {
        "phone": "p_sun_meilan",
        "name": "孙美兰",
        "gender": "female",
        "birth_year": 1967,
        "height": 160,
        "weight": 62,
        "waist": 78,
        "smoking": "never",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.QI_STAGNATION,
        "hospital": "南京鼓楼医院",
        "dx_year": 2020,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "缬沙坦", "dose": "80mg", "frequency": "每日一次", "start_date": "2020-07-01"},
            ]
        },
        "bp_base": (142, 88),
        "bp_sigma": (10, 7),
    },
    {
        "phone": "p_liu_changhe",
        "name": "刘长河",
        "gender": "male",
        "birth_year": 1949,
        "height": 170,
        "weight": 74,
        "waist": 90,
        "smoking": "former",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.0,
        "stress": "low",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.YANG_DEFICIENCY,
        "hospital": "沈阳盛京医院",
        "dx_year": 2008,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "氨氯地平", "dose": "5mg", "frequency": "每日一次", "start_date": "2008-02-15"},
                {"name": "替米沙坦", "dose": "40mg", "frequency": "每日一次", "start_date": "2010-08-20"},
            ]
        },
        "bp_base": (140, 85),
        "bp_sigma": (10, 7),
    },
    {
        "phone": "p_huang_xiaoming",
        "name": "黄晓明",
        "gender": "male",
        "birth_year": 1975,
        "height": 178,
        "weight": 90,
        "waist": 102,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.0,
        "stress": "high",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "hospital": "杭州浙医一院",
        "dx_year": 2022,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "氨氯地平", "dose": "10mg", "frequency": "每日一次", "start_date": "2022-03-01"},
            ]
        },
        "bp_base": (152, 95),
        "bp_sigma": (14, 9),
    },
    {
        "phone": "p_wu_guihua",
        "name": "吴桂花",
        "gender": "female",
        "birth_year": 1959,
        "height": 156,
        "weight": 58,
        "waist": 76,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.5,
        "stress": "low",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.BALANCED,
        "hospital": "西安第四军医大学西京医院",
        "dx_year": 2019,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "苯磺酸左氨氯地平", "dose": "2.5mg", "frequency": "每日一次", "start_date": "2019-11-10"},
            ]
        },
        "bp_base": (132, 82),
        "bp_sigma": (7, 5),
    },
    {
        "phone": "p_zhou_jianhua",
        "name": "周建华",
        "gender": "male",
        "birth_year": 1956,
        "height": 173,
        "weight": 80,
        "waist": 94,
        "smoking": "former",
        "drinking": "occasional",
        "exercise": "occasional",
        "sleep": 6.0,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION],
        "body_type": BodyType.BLOOD_STASIS,
        "hospital": "重庆第三军医大学新桥医院",
        "dx_year": 2014,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "卡维地洛", "dose": "12.5mg", "frequency": "每日两次", "start_date": "2014-07-08"},
                {"name": "厄贝沙坦氢氯噻嗪", "dose": "150mg/12.5mg", "frequency": "每日一次", "start_date": "2016-01-15"},
            ]
        },
        "bp_base": (150, 94),
        "bp_sigma": (13, 8),
    },
    # 糖尿病患者（8人）
    {
        "phone": "p_ma_lihua",
        "name": "马丽华",
        "gender": "female",
        "birth_year": 1965,
        "height": 162,
        "weight": 70,
        "waist": 88,
        "smoking": "never",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 7.0,
        "stress": "medium",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "hospital": "北京友谊医院",
        "dx_year": 2016,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2016-05-10"},
                {"name": "西格列汀", "dose": "100mg", "frequency": "每日一次", "start_date": "2019-03-01"},
            ]
        },
        "glucose_base": 8.2,
        "glucose_sigma": 1.5,
    },
    {
        "phone": "p_lin_dequan",
        "name": "林德全",
        "gender": "male",
        "birth_year": 1961,
        "height": 169,
        "weight": 76,
        "waist": 92,
        "smoking": "former",
        "drinking": "occasional",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.QI_DEFICIENCY,
        "hospital": "福建协和医院",
        "dx_year": 2012,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "1000mg", "frequency": "每日两次", "start_date": "2012-08-20"},
                {"name": "格列美脲", "dose": "2mg", "frequency": "每日一次", "start_date": "2014-02-10"},
            ]
        },
        "glucose_base": 9.0,
        "glucose_sigma": 2.0,
    },
    {
        "phone": "p_he_yumei",
        "name": "何玉梅",
        "gender": "female",
        "birth_year": 1957,
        "height": 158,
        "weight": 68,
        "waist": 86,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.0,
        "stress": "low",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.YIN_DEFICIENCY,
        "hospital": "中山大学附属第一医院",
        "dx_year": 2014,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "阿卡波糖", "dose": "50mg", "frequency": "每日三次", "start_date": "2014-10-05"},
                {"name": "达格列净", "dose": "10mg", "frequency": "每日一次", "start_date": "2021-01-15"},
            ]
        },
        "glucose_base": 7.5,
        "glucose_sigma": 1.2,
    },
    {
        "phone": "p_gao_shunfa",
        "name": "高顺发",
        "gender": "male",
        "birth_year": 1954,
        "height": 166,
        "weight": 82,
        "waist": 96,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.5,
        "stress": "high",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.DAMP_HEAT,
        "hospital": "哈尔滨医科大学附属第一医院",
        "dx_year": 2009,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "精蛋白生物合成人胰岛素（预混30R）", "dose": "14IU", "frequency": "早晚各一次", "start_date": "2015-06-01"},
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2009-12-10"},
            ]
        },
        "glucose_base": 11.5,
        "glucose_sigma": 3.0,
    },
    {
        "phone": "p_tan_guifang",
        "name": "谭桂芳",
        "gender": "female",
        "birth_year": 1968,
        "height": 160,
        "weight": 64,
        "waist": 82,
        "smoking": "never",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 7.5,
        "stress": "medium",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.QI_STAGNATION,
        "hospital": "长沙湘雅医院",
        "dx_year": 2019,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2019-04-20"},
            ]
        },
        "glucose_base": 7.8,
        "glucose_sigma": 1.3,
    },
    {
        "phone": "p_xiao_junliang",
        "name": "肖俊良",
        "gender": "male",
        "birth_year": 1970,
        "height": 176,
        "weight": 86,
        "waist": 96,
        "smoking": "former",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 6.0,
        "stress": "medium",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.YANG_DEFICIENCY,
        "hospital": "郑州大学第一附属医院",
        "dx_year": 2017,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "利格列汀", "dose": "5mg", "frequency": "每日一次", "start_date": "2017-09-10"},
                {"name": "二甲双胍", "dose": "1000mg", "frequency": "每日两次", "start_date": "2017-09-10"},
            ]
        },
        "glucose_base": 8.5,
        "glucose_sigma": 1.8,
    },
    {
        "phone": "p_peng_aijun",
        "name": "彭爱君",
        "gender": "female",
        "birth_year": 1960,
        "height": 155,
        "weight": 58,
        "waist": 78,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 8.0,
        "stress": "low",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.BALANCED,
        "hospital": "昆明医科大学第一附属医院",
        "dx_year": 2021,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日两次", "start_date": "2021-03-15"},
            ]
        },
        "glucose_base": 7.2,
        "glucose_sigma": 0.9,
    },
    {
        "phone": "p_fu_xiangsheng",
        "name": "傅祥生",
        "gender": "male",
        "birth_year": 1948,
        "height": 165,
        "weight": 72,
        "waist": 88,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.0,
        "stress": "high",
        "diseases": [DiseaseType.DIABETES_T2],
        "body_type": BodyType.BLOOD_STASIS,
        "hospital": "贵州医科大学附属医院",
        "dx_year": 2006,
        "medications_map": {
            DiseaseType.DIABETES_T2: [
                {"name": "甘精胰岛素", "dose": "18IU", "frequency": "每晚一次", "start_date": "2016-01-10"},
                {"name": "门冬胰岛素", "dose": "8IU", "frequency": "三餐前", "start_date": "2016-01-10"},
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2006-09-05"},
            ]
        },
        "glucose_base": 12.8,
        "glucose_sigma": 3.5,
    },
    # 高血压+糖尿病双病患者（7人）
    {
        "phone": "p_deng_xiulan",
        "name": "邓秀兰",
        "gender": "female",
        "birth_year": 1953,
        "height": 156,
        "weight": 72,
        "waist": 90,
        "smoking": "never",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.PHLEGM_DAMPNESS,
        "hospital": "天津医科大学总医院",
        "dx_year": 2011,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "苯磺酸氨氯地平", "dose": "5mg", "frequency": "每日一次", "start_date": "2011-03-20"},
                {"name": "厄贝沙坦", "dose": "150mg", "frequency": "每日一次", "start_date": "2013-07-10"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2013-01-15"},
                {"name": "沙格列汀", "dose": "5mg", "frequency": "每日一次", "start_date": "2018-04-20"},
            ],
        },
        "bp_base": (145, 90),
        "bp_sigma": (12, 8),
        "glucose_base": 9.2,
        "glucose_sigma": 2.0,
    },
    {
        "phone": "p_luo_shengquan",
        "name": "罗盛全",
        "gender": "male",
        "birth_year": 1950,
        "height": 167,
        "weight": 78,
        "waist": 95,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.0,
        "stress": "high",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.DAMP_HEAT,
        "hospital": "山东大学齐鲁医院",
        "dx_year": 2008,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "硝苯地平控释片", "dose": "60mg", "frequency": "每日一次", "start_date": "2008-07-05"},
                {"name": "螺内酯", "dose": "20mg", "frequency": "每日一次", "start_date": "2010-05-18"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "预混胰岛素30/70", "dose": "16IU/12IU", "frequency": "早晚各一次", "start_date": "2012-11-01"},
            ],
        },
        "bp_base": (165, 102),
        "bp_sigma": (16, 12),
        "glucose_base": 13.2,
        "glucose_sigma": 3.8,
    },
    {
        "phone": "p_jiang_sufen",
        "name": "蒋素芬",
        "gender": "female",
        "birth_year": 1960,
        "height": 159,
        "weight": 66,
        "waist": 84,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.0,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.YIN_DEFICIENCY,
        "hospital": "南昌大学第一附属医院",
        "dx_year": 2015,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "贝那普利", "dose": "10mg", "frequency": "每日一次", "start_date": "2015-06-10"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2015-06-10"},
                {"name": "达格列净", "dose": "10mg", "frequency": "每日一次", "start_date": "2020-09-15"},
            ],
        },
        "bp_base": (140, 88),
        "bp_sigma": (10, 7),
        "glucose_base": 8.0,
        "glucose_sigma": 1.5,
    },
    {
        "phone": "p_xu_mingde",
        "name": "许明德",
        "gender": "male",
        "birth_year": 1955,
        "height": 170,
        "weight": 80,
        "waist": 95,
        "smoking": "former",
        "drinking": "occasional",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.QI_DEFICIENCY,
        "hospital": "兰州大学第一医院",
        "dx_year": 2013,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "氨氯地平", "dose": "5mg", "frequency": "每日一次", "start_date": "2013-03-08"},
                {"name": "坎地沙坦", "dose": "8mg", "frequency": "每日一次", "start_date": "2015-08-20"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "格列齐特缓释片", "dose": "30mg", "frequency": "每日一次", "start_date": "2013-03-08"},
                {"name": "二甲双胍", "dose": "1000mg", "frequency": "每日两次", "start_date": "2013-03-08"},
            ],
        },
        "bp_base": (150, 93),
        "bp_sigma": (13, 9),
        "glucose_base": 9.8,
        "glucose_sigma": 2.2,
    },
    {
        "phone": "p_xie_yuqin",
        "name": "谢玉琴",
        "gender": "female",
        "birth_year": 1952,
        "height": 155,
        "weight": 62,
        "waist": 82,
        "smoking": "never",
        "drinking": "never",
        "exercise": "regular",
        "sleep": 7.5,
        "stress": "low",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.BLOOD_STASIS,
        "hospital": "石家庄河北医科大学第二医院",
        "dx_year": 2009,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "硝苯地平控释片", "dose": "30mg", "frequency": "每日一次", "start_date": "2009-05-12"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "甘精胰岛素", "dose": "14IU", "frequency": "每晚一次", "start_date": "2018-02-20"},
                {"name": "阿卡波糖", "dose": "50mg", "frequency": "每日三次", "start_date": "2009-05-12"},
            ],
        },
        "bp_base": (143, 89),
        "bp_sigma": (11, 7),
        "glucose_base": 8.8,
        "glucose_sigma": 1.8,
    },
    {
        "phone": "p_song_fengcai",
        "name": "宋凤彩",
        "gender": "female",
        "birth_year": 1957,
        "height": 158,
        "weight": 66,
        "waist": 84,
        "smoking": "never",
        "drinking": "never",
        "exercise": "occasional",
        "sleep": 6.5,
        "stress": "medium",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.QI_STAGNATION,
        "hospital": "合肥安徽医科大学第一附属医院",
        "dx_year": 2016,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "厄贝沙坦", "dose": "150mg", "frequency": "每日一次", "start_date": "2016-08-01"},
                {"name": "比索洛尔", "dose": "5mg", "frequency": "每日一次", "start_date": "2018-03-10"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2016-08-01"},
                {"name": "西格列汀", "dose": "100mg", "frequency": "每日一次", "start_date": "2019-11-20"},
            ],
        },
        "bp_base": (148, 92),
        "bp_sigma": (12, 8),
        "glucose_base": 9.5,
        "glucose_sigma": 2.0,
    },
    {
        "phone": "p_wu_dacai",
        "name": "吴大财",
        "gender": "male",
        "birth_year": 1946,
        "height": 163,
        "weight": 70,
        "waist": 90,
        "smoking": "current",
        "drinking": "occasional",
        "exercise": "never",
        "sleep": 5.0,
        "stress": "high",
        "diseases": [DiseaseType.HYPERTENSION, DiseaseType.DIABETES_T2],
        "body_type": BodyType.SPECIAL_DIATHESIS,
        "hospital": "太原山西医科大学第一医院",
        "dx_year": 2005,
        "medications_map": {
            DiseaseType.HYPERTENSION: [
                {"name": "硝苯地平控释片", "dose": "30mg", "frequency": "每日一次", "start_date": "2005-03-10"},
                {"name": "厄贝沙坦", "dose": "300mg", "frequency": "每日一次", "start_date": "2008-07-20"},
                {"name": "氢氯噻嗪", "dose": "25mg", "frequency": "每日一次", "start_date": "2012-01-05"},
            ],
            DiseaseType.DIABETES_T2: [
                {"name": "德谷胰岛素", "dose": "20IU", "frequency": "每晚一次", "start_date": "2019-05-10"},
                {"name": "二甲双胍", "dose": "500mg", "frequency": "每日三次", "start_date": "2005-03-10"},
            ],
        },
        "bp_base": (168, 105),
        "bp_sigma": (18, 12),
        "glucose_base": 14.5,
        "glucose_sigma": 4.0,
    },
]


# ════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════

def gaussian_clamp(base: float, sigma: float, lo: float, hi: float) -> float:
    v = random.gauss(base, sigma)
    return round(max(lo, min(hi, v)), 1)


def rand_datetime_on_day(d: date, hour_lo: int = 6, hour_hi: int = 22) -> datetime:
    hour = random.randint(hour_lo, hour_hi)
    minute = random.randint(0, 59)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


async def get_or_create_user(db: AsyncSession, phone: str, name: str, password: str = "Demo@123456") -> User:
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            phone=phone,
            name=name,
            password_hash=hash_password(password),
            role=UserRole.PATIENT,
        )
        db.add(user)
        await db.flush()
        print(f"    + 患者: {name} ({phone})")
    return user


# ════════════════════════════════════════════════════════
# 1. 健康档案 + 慢病记录
# ════════════════════════════════════════════════════════

async def seed_health_profile(db: AsyncSession, user: User, p: dict):
    result = await db.execute(
        select(HealthProfile).where(HealthProfile.user_id == user.id)
    )
    if result.scalar_one_or_none() is not None:
        return
    birth = date(p["birth_year"], random.randint(1, 12), random.randint(1, 28))
    hp = HealthProfile(
        user_id=user.id,
        gender=p["gender"],
        birth_date=birth,
        height_cm=p["height"],
        weight_kg=p["weight"],
        waist_cm=p["waist"],
        past_history={"conditions": [d.value for d in p["diseases"]]},
        family_history={"conditions": random.choice([[], ["HYPERTENSION"], ["DIABETES_T2"], ["HYPERTENSION", "DIABETES_T2"]])},
        allergy_history={"drugs": [], "foods": []},
        smoking=p["smoking"],
        drinking=p["drinking"],
        exercise_frequency=p["exercise"],
        sleep_hours=p["sleep"],
        stress_level=p["stress"],
    )
    db.add(hp)


async def seed_disease_records(db: AsyncSession, user: User, p: dict):
    for disease in p["diseases"]:
        result = await db.execute(
            select(ChronicDiseaseRecord).where(
                ChronicDiseaseRecord.user_id == user.id,
                ChronicDiseaseRecord.disease_type == disease,
            )
        )
        if result.scalar_one_or_none() is not None:
            continue
        dx_date = date(p["dx_year"], random.randint(1, 12), random.randint(1, 28))
        meds = p.get("medications_map", {}).get(disease, [])
        if disease == DiseaseType.HYPERTENSION:
            target = {"systolic_target": 130, "diastolic_target": 80}
            complications = random.choice([[], ["左心室肥大"], ["微量蛋白尿"]])
        else:
            target = {"hba1c_target": 7.0, "fasting_target": 7.0}
            complications = random.choice([[], ["周围神经病变"], ["视网膜病变"], ["肾病"]])
        cdr = ChronicDiseaseRecord(
            user_id=user.id,
            disease_type=disease,
            diagnosed_at=dx_date,
            diagnosed_hospital=p["hospital"],
            medications=meds,
            complications=complications,
            target_values=target,
            is_active=True,
        )
        db.add(cdr)


# ════════════════════════════════════════════════════════
# 2. 健康指标历史（60天）
# ════════════════════════════════════════════════════════

async def seed_indicators(db: AsyncSession, user: User, p: dict) -> list[HealthIndicator]:
    """生成近 60 天的指标记录，返回新建的列表（用于后续预警）"""
    new_indicators = []

    # 判断是否已有数据
    result = await db.execute(
        select(HealthIndicator).where(HealthIndicator.user_id == user.id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return new_indicators

    has_bp = "bp_base" in p
    has_glucose = "glucose_base" in p

    for day_offset in range(60, -1, -1):
        d = TODAY - timedelta(days=day_offset)

        # 偶尔漏测（模拟真实依从性）
        miss_chance = 0.12
        if random.random() < miss_chance:
            continue

        if has_bp:
            sys_base, dia_base = p["bp_base"]
            sys_sigma, dia_sigma = p["bp_sigma"]
            # 每天早晨一次
            systolic = int(gaussian_clamp(sys_base, sys_sigma, 90, 220))
            diastolic = int(gaussian_clamp(dia_base, dia_sigma, 60, 140))
            ind = HealthIndicator(
                user_id=user.id,
                indicator_type=IndicatorType.BLOOD_PRESSURE,
                values={"systolic": systolic, "diastolic": diastolic},
                scene="morning",
                recorded_at=rand_datetime_on_day(d, 6, 9),
            )
            db.add(ind)
            new_indicators.append(ind)

            # 睡前再测一次（60%概率）
            if random.random() < 0.6:
                systolic2 = int(gaussian_clamp(sys_base + 3, sys_sigma, 90, 220))
                diastolic2 = int(gaussian_clamp(dia_base + 2, dia_sigma, 60, 140))
                ind2 = HealthIndicator(
                    user_id=user.id,
                    indicator_type=IndicatorType.BLOOD_PRESSURE,
                    values={"systolic": systolic2, "diastolic": diastolic2},
                    scene="evening",
                    recorded_at=rand_datetime_on_day(d, 20, 22),
                )
                db.add(ind2)
                new_indicators.append(ind2)

        if has_glucose:
            glu_base = p["glucose_base"]
            glu_sigma = p["glucose_sigma"]
            fasting_val = gaussian_clamp(glu_base, glu_sigma, 3.0, 25.0)
            ind_g = HealthIndicator(
                user_id=user.id,
                indicator_type=IndicatorType.BLOOD_GLUCOSE,
                values={"scene": "fasting", "value": fasting_val},
                scene="fasting",
                recorded_at=rand_datetime_on_day(d, 6, 8),
            )
            db.add(ind_g)
            new_indicators.append(ind_g)

            # 餐后血糖（50%概率）
            if random.random() < 0.5:
                postmeal_val = gaussian_clamp(glu_base * 1.3, glu_sigma * 1.2, 3.5, 30.0)
                ind_pm = HealthIndicator(
                    user_id=user.id,
                    indicator_type=IndicatorType.BLOOD_GLUCOSE,
                    values={"scene": "postmeal_2h", "value": postmeal_val},
                    scene="postmeal_2h",
                    recorded_at=rand_datetime_on_day(d, 9, 14),
                )
                db.add(ind_pm)
                new_indicators.append(ind_pm)

        # 体重（每周一次）
        if d.weekday() == 0 and (has_bp or has_glucose):  # 周一
            weight_val = gaussian_clamp(p["weight"], 1.5, 40, 150)
            ind_w = HealthIndicator(
                user_id=user.id,
                indicator_type=IndicatorType.WEIGHT,
                values={"value": weight_val},
                recorded_at=rand_datetime_on_day(d, 7, 8),
            )
            db.add(ind_w)

    await db.flush()
    return new_indicators


# ════════════════════════════════════════════════════════
# 3. 体质评估
# ════════════════════════════════════════════════════════

async def seed_constitution_assessment(db: AsyncSession, user: User, body_type: BodyType, questions: list):
    result = await db.execute(
        select(ConstitutionAssessment).where(ConstitutionAssessment.user_id == user.id)
    )
    if result.scalar_one_or_none() is not None:
        return

    # 按体质分组问题
    questions_by_type: dict[BodyType, list] = {}
    for q in questions:
        questions_by_type.setdefault(q.body_type, []).append(q)

    assessment = ConstitutionAssessment(
        user_id=user.id,
        status=AssessmentStatus.SCORED,
        main_type=body_type,
        submitted_at=NOW - timedelta(days=random.randint(20, 60)),
        scored_at=NOW - timedelta(days=random.randint(10, 19)),
    )
    db.add(assessment)
    await db.flush()

    # 生成各体质的得分
    result_data = {}
    secondary = []
    for bt, qs in questions_by_type.items():
        if bt == body_type:
            # 主体质：偏高分
            answers_vals = [random.choice([4, 5]) for _ in qs]
        else:
            # 非主体质：偏低分，但随机有一些偏高
            answers_vals = [random.choice([1, 2, 2, 3]) for _ in qs]

        raw = sum(answers_vals)
        n = len(qs)
        converted = round((raw - n) / (4 * n) * 100)

        if bt == body_type:
            level = "yes"
        elif converted >= 40:
            level = "tendency"
            secondary.append(bt.value)
        else:
            level = "no"

        result_data[bt.value] = {
            "raw_score": raw,
            "converted_score": converted,
            "level": level,
        }

        for q, val in zip(qs, answers_vals):
            ans = ConstitutionAnswer(
                assessment_id=assessment.id,
                question_id=q.id,
                answer_value=val,
            )
            db.add(ans)

    assessment.result = result_data
    assessment.secondary_types = secondary


# ════════════════════════════════════════════════════════
# 4. 随访计划 + 任务 + 打卡
# ════════════════════════════════════════════════════════

async def seed_followup(db: AsyncSession, user: User, p: dict):
    result = await db.execute(
        select(FollowupPlan).where(FollowupPlan.user_id == user.id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return

    # 选择主病种
    primary_disease = p["diseases"][0]
    plan_start = TODAY - timedelta(days=random.randint(20, 45))
    plan_end = plan_start + timedelta(days=30)
    plan_status = FollowupStatus.ACTIVE if plan_end >= TODAY else FollowupStatus.COMPLETED

    plan = FollowupPlan(
        user_id=user.id,
        disease_type=primary_disease,
        status=plan_status,
        start_date=plan_start,
        end_date=plan_end,
    )
    db.add(plan)
    await db.flush()

    # 生成任务（每天的打卡任务）
    task_defs = _get_task_defs(primary_disease)

    for day_offset in range(31):
        task_date = plan_start + timedelta(days=day_offset)
        if task_date > TODAY:
            break  # 未来的不生成

        for tdef in task_defs:
            task = FollowupTask(
                plan_id=plan.id,
                task_type=tdef["task_type"],
                name=tdef["name"],
                scheduled_date=task_date,
                required=tdef["required"],
                meta=tdef.get("meta", {}),
            )
            db.add(task)
            await db.flush()

            # 生成打卡（过去的任务按依从性率）
            compliance_rate = _get_compliance_rate(p)
            if random.random() < compliance_rate:
                checkin_val, note = _gen_checkin_value(tdef, p)
                ci = CheckIn(
                    task_id=task.id,
                    user_id=user.id,
                    status=CheckInStatus.DONE,
                    value=checkin_val,
                    note=note,
                    checked_at=datetime(
                        task_date.year, task_date.month, task_date.day,
                        random.randint(7, 22), random.randint(0, 59),
                        tzinfo=timezone.utc,
                    ),
                )
                db.add(ci)
            else:
                ci = CheckIn(
                    task_id=task.id,
                    user_id=user.id,
                    status=CheckInStatus.MISSED,
                )
                db.add(ci)


def _get_task_defs(disease: DiseaseType) -> list[dict]:
    if disease == DiseaseType.HYPERTENSION:
        return [
            {"task_type": TaskType.INDICATOR_REPORT, "name": "记录血压（晨起）", "required": True,
             "meta": {"indicator_type": "BLOOD_PRESSURE", "scene": "morning"}},
            {"task_type": TaskType.MEDICATION, "name": "按时服用降压药", "required": True, "meta": {}},
            {"task_type": TaskType.EXERCISE, "name": "适量运动30分钟", "required": False, "meta": {}},
        ]
    else:
        return [
            {"task_type": TaskType.INDICATOR_REPORT, "name": "记录空腹血糖", "required": True,
             "meta": {"indicator_type": "BLOOD_GLUCOSE", "scene": "fasting"}},
            {"task_type": TaskType.MEDICATION, "name": "按时服用降糖药", "required": True, "meta": {}},
            {"task_type": TaskType.EXERCISE, "name": "餐后散步20分钟", "required": False, "meta": {}},
        ]


def _get_compliance_rate(p: dict) -> float:
    base = 0.78
    if p["exercise"] == "regular":
        base += 0.10
    elif p["exercise"] == "never":
        base -= 0.15
    if p["stress"] == "high":
        base -= 0.10
    elif p["stress"] == "low":
        base += 0.05
    return max(0.4, min(0.95, base))


def _gen_checkin_value(tdef: dict, p: dict) -> tuple[dict, str | None]:
    meta = tdef.get("meta", {})
    if tdef["task_type"] == TaskType.INDICATOR_REPORT:
        if meta.get("indicator_type") == "BLOOD_PRESSURE":
            s_base, d_base = p.get("bp_base", (140, 88))
            s_sigma, d_sigma = p.get("bp_sigma", (10, 7))
            return {
                "systolic": int(gaussian_clamp(s_base, s_sigma, 90, 220)),
                "diastolic": int(gaussian_clamp(d_base, d_sigma, 60, 140)),
            }, None
        elif meta.get("indicator_type") == "BLOOD_GLUCOSE":
            g_base = p.get("glucose_base", 8.0)
            g_sigma = p.get("glucose_sigma", 1.5)
            return {"value": gaussian_clamp(g_base, g_sigma, 3.0, 25.0)}, None
    elif tdef["task_type"] == TaskType.MEDICATION:
        return {"done": True}, random.choice([None, None, None, "已按时服药", "饭后服用"])
    elif tdef["task_type"] == TaskType.EXERCISE:
        minutes = random.randint(20, 50)
        return {"done": True, "minutes": minutes}, f"运动{minutes}分钟"
    return {"done": True}, None


# ════════════════════════════════════════════════════════
# 5. 预警事件
# ════════════════════════════════════════════════════════

async def seed_alert_events(db: AsyncSession, user: User, p: dict, rules: list[AlertRule]):
    result = await db.execute(
        select(AlertEvent).where(AlertEvent.user_id == user.id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return

    # 高风险患者（sigma大或base高）模拟几次触发预警
    has_bp = "bp_base" in p
    has_glucose = "glucose_base" in p

    bp_rules = [r for r in rules if r.indicator_type == IndicatorType.BLOOD_PRESSURE]
    glu_rules = [r for r in rules if r.indicator_type == IndicatorType.BLOOD_GLUCOSE]

    events_created = 0
    max_events = random.randint(1, 4) if p["stress"] == "high" else random.randint(0, 2)

    for _ in range(max_events):
        if has_bp and bp_rules and random.random() < 0.6:
            sys_base, _ = p["bp_base"]
            sys_sigma, _ = p["bp_sigma"]
            # 偶发性高值
            danger_systolic = int(gaussian_clamp(sys_base + 25, sys_sigma * 1.5, 150, 220))
            danger_diastolic = int(gaussian_clamp(p["bp_base"][1] + 15, p["bp_sigma"][1], 100, 140))
            matched_rule = None
            for rule in sorted(bp_rules, key=lambda r: r.severity.value, reverse=True):
                for cond in rule.conditions:
                    field = cond["field"]
                    val = danger_systolic if field == "systolic" else danger_diastolic
                    op = cond["op"]
                    threshold = cond["value"]
                    if eval(f"{val} {op} {threshold}"):
                        matched_rule = rule
                        break
                if matched_rule:
                    break
            if matched_rule:
                tval = {"systolic": danger_systolic, "diastolic": danger_diastolic}
                msg = matched_rule.message_template.format(**tval)
                days_ago = random.randint(1, 30)
                evt = AlertEvent(
                    user_id=user.id,
                    rule_id=matched_rule.id,
                    severity=matched_rule.severity,
                    status=AlertStatus.CLOSED if days_ago > 7 else random.choice([AlertStatus.OPEN, AlertStatus.ACKED, AlertStatus.CLOSED]),
                    trigger_value=tval,
                    message=msg,
                    created_at=NOW - timedelta(days=days_ago),
                )
                if evt.status != AlertStatus.OPEN:
                    evt.acked_at = NOW - timedelta(days=days_ago - 1)
                    evt.handler_note = random.choice([
                        "已联系患者，建议休息并复测",
                        "电话随访，指导患者按医嘱服药",
                        "嘱患者明日门诊就诊",
                        "情绪激动后血压升高，已疏导",
                    ])
                if evt.status == AlertStatus.CLOSED:
                    evt.closed_at = NOW - timedelta(days=max(0, days_ago - 2))
                db.add(evt)
                events_created += 1

        if has_glucose and glu_rules and random.random() < 0.6:
            g_base = p["glucose_base"]
            g_sigma = p["glucose_sigma"]
            danger_glu = gaussian_clamp(g_base + 5, g_sigma * 1.5, 7.0, 28.0)
            matched_rule = None
            for rule in sorted(glu_rules, key=lambda r: r.severity.value, reverse=True):
                for cond in rule.conditions:
                    op = cond["op"]
                    threshold = cond["value"]
                    if eval(f"{danger_glu} {op} {threshold}"):
                        matched_rule = rule
                        break
                if matched_rule:
                    break
            if matched_rule:
                tval = {"value": danger_glu}
                msg = matched_rule.message_template.format(**tval)
                days_ago = random.randint(1, 30)
                evt = AlertEvent(
                    user_id=user.id,
                    rule_id=matched_rule.id,
                    severity=matched_rule.severity,
                    status=AlertStatus.CLOSED if days_ago > 7 else random.choice([AlertStatus.OPEN, AlertStatus.ACKED, AlertStatus.CLOSED]),
                    trigger_value=tval,
                    message=msg,
                    created_at=NOW - timedelta(days=days_ago),
                )
                if evt.status != AlertStatus.OPEN:
                    evt.acked_at = NOW - timedelta(days=days_ago - 1)
                    evt.handler_note = random.choice([
                        "电话联系患者，询问饮食情况",
                        "嘱患者检查是否漏服药物",
                        "建议患者及时补充水分，卧床休息",
                        "已安排门诊复查",
                    ])
                if evt.status == AlertStatus.CLOSED:
                    evt.closed_at = NOW - timedelta(days=max(0, days_ago - 2))
                db.add(evt)
                events_created += 1


# ════════════════════════════════════════════════════════
# 6. 居民档案（PatientArchive）+ 家庭档案
# ════════════════════════════════════════════════════════

async def seed_patient_archive(db: AsyncSession, user: User, p: dict) -> "PatientArchive | None":
    """为每位患者创建一份居民档案（幂等，按 user_id 去重）。"""
    result = await db.execute(
        select(PatientArchive).where(PatientArchive.user_id == user.id)
    )
    if result.scalar_one_or_none() is not None:
        return None

    birth_year = p["birth_year"]
    age = 2026 - birth_year
    h = abs(hash(p["phone"]))
    birth_month = (h % 11) + 1
    birth_day = (h % 27) + 1

    # 档案类型判定
    bp_high = p.get("bp_base", (0, 0))[0] >= 165
    glu_high = p.get("glucose_base", 0) >= 14.0
    if age >= 65:
        atype = ArchiveType.ELDERLY
    elif bp_high or glu_high or (age >= 60 and p["stress"] == "high"):
        atype = ArchiveType.KEY_FOCUS
    elif p["gender"] == "female":
        atype = ArchiveType.FEMALE
    else:
        atype = ArchiveType.NORMAL

    province, city = _CITIES[h % len(_CITIES)]
    district = _DISTRICTS[h % len(_DISTRICTS)]

    archive = PatientArchive(
        user_id=user.id,
        name=p["name"],
        gender=p["gender"],
        birth_date=date(birth_year, birth_month, birth_day),
        ethnicity="汉族",
        occupation=_OCCUPATIONS[h % len(_OCCUPATIONS)],
        id_type=IdType.ID_CARD,
        id_number=_gen_id_number(birth_year, birth_month, birth_day, p["gender"], h),
        phone=_gen_phone(p["phone"]),
        province=province,
        city=city,
        district=district,
        address=f"{district}幸福路{(h % 200) + 1}号",
        emergency_contact_name=f"{p['name'][0]}某某",
        emergency_contact_phone=_gen_phone(p["phone"] + "_ec"),
        emergency_contact_relation="子女",
        archive_type=atype,
        tags=[d.value for d in p["diseases"]],
        past_history=[d.value for d in p["diseases"]],
        is_deleted=False,
    )
    db.add(archive)
    await db.flush()
    return archive


async def seed_family_archives(db: AsyncSession, archive_ids: list) -> None:
    """创建5个示例家庭档案（幂等，按 family_name 去重）。"""
    families = [
        {"name": "张家（朝阳）", "address": "北京市朝阳区幸福路1号", "member_count": 3},
        {"name": "李家（海淀）", "address": "北京市海淀区知春路25号", "member_count": 4},
        {"name": "王家（西城）", "address": "北京市西城区长安街10号", "member_count": 2},
        {"name": "赵家（东城）", "address": "北京市东城区建国门内大街5号", "member_count": 3},
        {"name": "陈家（丰台）", "address": "北京市丰台区丰台路88号", "member_count": 2},
    ]
    created_families = []
    for i, fam in enumerate(families):
        result = await db.execute(
            select(FamilyArchive).where(FamilyArchive.family_name == fam["name"])
        )
        if result.scalar_one_or_none() is not None:
            continue
        fa = FamilyArchive(
            family_name=fam["name"],
            address=fam["address"],
            member_count=fam["member_count"],
        )
        db.add(fa)
        await db.flush()
        created_families.append(fa)
        # 关联部分档案成员
        relations = ["户主", "配偶", "子女", "父母"]
        for j, aid in enumerate(archive_ids[i * 2: i * 2 + fam["member_count"]]):
            member = ArchiveFamilyMember(
                family_id=fa.id,
                archive_id=aid,
                relation=relations[j % len(relations)],
            )
            db.add(member)
    await db.flush()
    if created_families:
        print(f"  ✓ 家庭档案：{len(created_families)} 个新增")


# ════════════════════════════════════════════════════════
# 7. 临床文档（HIS/LIS 模拟数据，链接到 archive_id）
# ════════════════════════════════════════════════════════

_DEPTS = ["中医科", "内分泌科", "心内科", "全科诊室", "老年科"]
_DOCTORS_NAMES = ["张医生", "李医生", "王医生", "赵医生"]


_EXAM_PARTS = ["胸部", "腹部", "头颅", "颈椎", "腰椎", "膝关节"]
_IMAGE_FINDINGS = [
    "双肺纹理清晰，未见明显渗出及实变影，心影大小正常。",
    "肝脏大小形态正常，实质回声均匀，胆囊壁光滑，胆管未见扩张。",
    "颈椎生理曲度变直，C3-C5椎间隙略窄，未见明显骨质破坏。",
    "腰椎退行性改变，L4-L5椎间盘膨出，椎管未见明显狭窄。",
    "双膝关节间隙稍窄，软骨下骨质硬化，边缘骨赘形成。",
]

_PRESCRIPTIONS = [
    [{"name": "苯磺酸氨氯地平片", "dose": "5mg", "freq": "每日一次", "days": 30},
     {"name": "厄贝沙坦片", "dose": "150mg", "freq": "每日一次", "days": 30}],
    [{"name": "复方丹参片", "dose": "3片", "freq": "每日三次", "days": 14},
     {"name": "血塞通软胶囊", "dose": "2粒", "freq": "每日两次", "days": 14}],
    [{"name": "二甲双胍缓释片", "dose": "500mg", "freq": "每日两次", "days": 30},
     {"name": "阿卡波糖片", "dose": "50mg", "freq": "每餐随第一口饭嚼服", "days": 30}],
    [{"name": "阿托伐他汀钙片", "dose": "20mg", "freq": "每晚一次", "days": 30},
     {"name": "阿司匹林肠溶片", "dose": "100mg", "freq": "每日一次", "days": 30}],
    [{"name": "六味地黄丸", "dose": "8粒", "freq": "每日两次", "days": 14},
     {"name": "金匮肾气丸", "dose": "20粒", "freq": "每日两次", "days": 14}],
]


def _make_lab_content(p: dict, idx: int) -> dict:
    diseases = p.get("diseases", [])
    has_dm = any("糖尿病" in str(d) for d in diseases)
    has_htn = any("高血压" in str(d) for d in diseases)
    items = [
        {"item_code": "FBG", "item_name": "空腹血糖",
         "value": f"{random.uniform(6.5, 10.2):.1f}" if has_dm else f"{random.uniform(4.5, 6.1):.1f}",
         "unit": "mmol/L", "ref_range": "3.9-6.1",
         "abnormal_flag": "H" if has_dm else "N"},
        {"item_code": "HbA1c", "item_name": "糖化血红蛋白",
         "value": f"{random.uniform(7.0, 10.5):.1f}" if has_dm else f"{random.uniform(4.5, 6.0):.1f}",
         "unit": "%", "ref_range": "4.0-6.5",
         "abnormal_flag": "H" if has_dm else "N"},
        {"item_code": "SBP", "item_name": "收缩压",
         "value": str(random.randint(145, 175) if has_htn else random.randint(110, 130)),
         "unit": "mmHg", "ref_range": "90-140",
         "abnormal_flag": "H" if has_htn else "N"},
        {"item_code": "TC", "item_name": "总胆固醇",
         "value": f"{random.uniform(4.5, 7.2):.2f}", "unit": "mmol/L", "ref_range": "2.8-5.17",
         "abnormal_flag": "H" if random.random() > 0.55 else "N"},
        {"item_code": "TG", "item_name": "甘油三酯",
         "value": f"{random.uniform(1.0, 3.2):.2f}", "unit": "mmol/L", "ref_range": "0.45-1.70",
         "abnormal_flag": "H" if random.random() > 0.5 else "N"},
        {"item_code": "Cr", "item_name": "血肌酐",
         "value": f"{random.uniform(65, 120):.1f}", "unit": "μmol/L", "ref_range": "44-106",
         "abnormal_flag": "H" if random.random() > 0.75 else "N"},
        {"item_code": "UA", "item_name": "尿酸",
         "value": f"{random.uniform(280, 520):.1f}", "unit": "μmol/L", "ref_range": "155-428",
         "abnormal_flag": "H" if random.random() > 0.6 else "N"},
    ]
    return {"items": items, "report_conclusion": "部分指标偏高，建议复查并调整治疗方案"}


async def _count_by_type(db: AsyncSession, archive_id, doc_type: str) -> int:
    from sqlalchemy import func as sqlfunc
    return await db.scalar(
        select(sqlfunc.count()).select_from(ClinicalDocument).where(
            ClinicalDocument.archive_id == archive_id,
            ClinicalDocument.doc_type == doc_type,
        )
    ) or 0


async def seed_clinical_documents(db: AsyncSession, archive: PatientArchive, p: dict) -> None:
    """为每位患者创建近60天的四类临床文档（按 doc_type 幂等，可增量补充）。"""
    h = abs(hash(p["phone"]))
    dept = _DEPTS[h % len(_DEPTS)]
    doctor = _DOCTORS_NAMES[h % len(_DOCTORS_NAMES)]
    diagnosis = "、".join(str(d.value) for d in p.get("diseases", [])) or "慢性病复诊"

    # ── 就诊记录（6条）──────────────────────────────
    if await _count_by_type(db, archive.id, "ENCOUNTER") == 0:
        for i in range(6):
            doc_date = NOW - timedelta(days=random.randint(3, 58))
            db.add(ClinicalDocument(
                archive_id=archive.id, patient_name=p["name"],
                doc_type="ENCOUNTER", source_system="HIS",
                dept=dept, doctor=doctor, doc_date=doc_date,
                external_ref_no=f"HIS-{uuid.uuid4().hex[:8].upper()}",
                encounter_ref=f"V{uuid.uuid4().hex[:6].upper()}",
                content={
                    "encounter_type": ["门诊", "门诊", "门诊", "急诊"][i % 4],
                    "chief_complaint": ["例行复诊", "头晕乏力", "血压波动", "慢病随访管理"][i % 4],
                    "diagnosis": diagnosis,
                    "physical_exam": f"血压{random.randint(130,160)}/{random.randint(75,100)}mmHg，心率{random.randint(65,85)}次/分",
                    "plan": "继续当前治疗方案，调整用药，定期复查",
                },
                sync_mode="AUTO",
            ))

    # ── 检验报告（4条）──────────────────────────────
    if await _count_by_type(db, archive.id, "LAB_REPORT") == 0:
        for i in range(4):
            doc_date = NOW - timedelta(days=random.randint(5, 55))
            db.add(ClinicalDocument(
                archive_id=archive.id, patient_name=p["name"],
                doc_type="LAB_REPORT", source_system="LIS",
                dept=dept, doctor=doctor,
                doc_date=doc_date - timedelta(hours=2),
                external_ref_no=f"LIS-{uuid.uuid4().hex[:8].upper()}",
                content=_make_lab_content(p, i),
                sync_mode="AUTO",
            ))

    # ── 处方（3条）────────────────────────────────────
    if await _count_by_type(db, archive.id, "PRESCRIPTION") == 0:
        rx_pool = _PRESCRIPTIONS
        for i in range(3):
            doc_date = NOW - timedelta(days=random.randint(5, 50))
            drugs = rx_pool[(h + i) % len(rx_pool)]
            db.add(ClinicalDocument(
                archive_id=archive.id, patient_name=p["name"],
                doc_type="PRESCRIPTION", source_system="HIS",
                dept=dept, doctor=doctor, doc_date=doc_date,
                external_ref_no=f"RX-{uuid.uuid4().hex[:8].upper()}",
                content={
                    "drugs": drugs,
                    "diagnosis": diagnosis,
                    "note": "按医嘱服药，定期复查，如有不适及时就诊",
                },
                sync_mode="AUTO",
            ))

    # ── 影像报告（2条）──────────────────────────────
    if await _count_by_type(db, archive.id, "IMAGE_REPORT") == 0:
        for i in range(2):
            doc_date = NOW - timedelta(days=random.randint(10, 60))
            part = _EXAM_PARTS[(h + i) % len(_EXAM_PARTS)]
            finding = _IMAGE_FINDINGS[(h + i) % len(_IMAGE_FINDINGS)]
            db.add(ClinicalDocument(
                archive_id=archive.id, patient_name=p["name"],
                doc_type="IMAGE_REPORT", source_system="PACS",
                dept=dept, doctor=doctor, doc_date=doc_date,
                external_ref_no=f"PACS-{uuid.uuid4().hex[:8].upper()}",
                content={
                    "exam_part": part,
                    "exam_method": ["X光", "CT", "超声", "MRI"][i % 4],
                    "findings": finding,
                    "impression": "建议结合临床综合判断，定期复查",
                    "image_url": None,
                },
                sync_mode="AUTO",
            ))

    await db.flush()


# ════════════════════════════════════════════════════════
# 7. 量表库 & 健康评估记录
# ════════════════════════════════════════════════════════

_BUILTIN_SCALES = [
    {
        "code": "PHQ9",
        "name": "患者健康问卷-9（PHQ-9）抑郁症筛查量表",
        "scale_type": "MENTAL_HEALTH",
        "description": "患者健康问卷-9，用于筛查和评估抑郁症状的严重程度，总分0-27分",
        "total_score": 27,
        "scoring_rule": '{"method":"sum"}',
        "level_rules": '[{"min":0,"max":4,"level":"NONE","label":"无抑郁"},{"min":5,"max":9,"level":"MILD","label":"轻度抑郁"},{"min":10,"max":14,"level":"MODERATE","label":"中度抑郁"},{"min":15,"max":27,"level":"SEVERE","label":"重度抑郁"}]',
        "estimated_minutes": 5,
        "is_builtin": True,
    },
    {
        "code": "GAD7",
        "name": "广泛性焦虑障碍量表（GAD-7）",
        "scale_type": "MENTAL_HEALTH",
        "description": "广泛性焦虑障碍量表，用于筛查和评估焦虑症状，总分0-21分",
        "total_score": 21,
        "scoring_rule": '{"method":"sum"}',
        "level_rules": '[{"min":0,"max":4,"level":"NONE","label":"无焦虑"},{"min":5,"max":9,"level":"MILD","label":"轻度焦虑"},{"min":10,"max":14,"level":"MODERATE","label":"中度焦虑"},{"min":15,"max":21,"level":"SEVERE","label":"重度焦虑"}]',
        "estimated_minutes": 5,
        "is_builtin": True,
    },
    {
        "code": "MMSE",
        "name": "简易精神状态检查量表（MMSE）",
        "scale_type": "COGNITIVE",
        "description": "评估记忆力、定向力、语言能力等认知功能，总分0-30分，用于筛查认知障碍",
        "total_score": 30,
        "scoring_rule": '{"method":"sum"}',
        "level_rules": '[{"min":27,"max":30,"level":"NORMAL","label":"认知功能正常"},{"min":21,"max":26,"level":"MILD","label":"轻度认知障碍"},{"min":10,"max":20,"level":"MODERATE","label":"中度认知障碍"},{"min":0,"max":9,"level":"SEVERE","label":"重度认知障碍"}]',
        "estimated_minutes": 10,
        "is_builtin": True,
    },
    {
        "code": "ADL",
        "name": "日常生活能力量表（ADL）",
        "scale_type": "FUNCTION",
        "description": "评估老年人日常生活自理能力，包括躯体自理和工具性日常生活活动能力",
        "total_score": 100,
        "scoring_rule": '{"method":"sum"}',
        "level_rules": '[{"min":80,"max":100,"level":"NORMAL","label":"生活自理"},{"min":60,"max":79,"level":"MILD","label":"轻度依赖"},{"min":40,"max":59,"level":"MODERATE","label":"中度依赖"},{"min":0,"max":39,"level":"SEVERE","label":"重度依赖"}]',
        "estimated_minutes": 8,
        "is_builtin": True,
    },
]

_SCALE_RECORD_DATA = [
    {
        "patient_name": "张伟",
        "scale_code": "PHQ9",
        "total_score": 12.0,
        "level": "中度抑郁",
        "conclusion": "评估结果提示中度抑郁症状（PHQ-9总分12分），建议进一步进行心理科专科评估，给予心理支持和必要的药物治疗，并加强随访管理。",
        "answers": '{"q1":2,"q2":2,"q3":1,"q4":2,"q5":1,"q6":1,"q7":1,"q8":1,"q9":1}',
        "completed_days_ago": 15,
    },
    {
        "patient_name": "李芳",
        "scale_code": "GAD7",
        "total_score": 8.0,
        "level": "轻度焦虑",
        "conclusion": "评估结果提示轻度焦虑症状（GAD-7总分8分），建议心理疏导和放松训练，定期复评。",
        "answers": '{"q1":1,"q2":2,"q3":1,"q4":1,"q5":1,"q6":1,"q7":1}',
        "completed_days_ago": 20,
    },
    {
        "patient_name": "王国华",
        "scale_code": "MMSE",
        "total_score": 28.0,
        "level": "认知功能正常",
        "conclusion": "认知功能评估正常（MMSE总分28分），建议定期复查维持监测，注意健康生活方式。",
        "answers": None,
        "completed_days_ago": 12,
    },
    {
        "patient_name": "陈秀英",
        "scale_code": "ADL",
        "total_score": None,
        "level": None,
        "conclusion": None,
        "answers": None,
        "completed_days_ago": None,  # DRAFT
    },
    {
        "patient_name": "赵俊民",
        "scale_code": "PHQ9",
        "total_score": 6.0,
        "level": "轻度抑郁",
        "conclusion": "评估结果提示轻度抑郁症状（PHQ-9总分6分），建议心理健康宣教和情绪调节指导。",
        "answers": '{"q1":1,"q2":1,"q3":1,"q4":1,"q5":1,"q6":1,"q7":0,"q8":0,"q9":0}',
        "completed_days_ago": 8,
    },
]


async def seed_scales_and_records(db: AsyncSession):
    """创建内置量表和健康评估记录（幂等）。"""
    from sqlalchemy import and_
    import json

    # 1. 创建内置量表（若不存在）
    scales_by_code: dict = {}
    for s_data in _BUILTIN_SCALES:
        r = await db.execute(select(Scale).where(Scale.code == s_data["code"]))
        scale = r.scalar_one_or_none()
        if scale is None:
            scale = Scale(**s_data, is_active=True, version=1)
            db.add(scale)
            await db.flush()
            print(f"    + 量表: {s_data['name']}")
        scales_by_code[s_data["code"]] = scale

    # 2. 创建评估记录
    for rec in _SCALE_RECORD_DATA:
        pa_r = await db.execute(
            select(PatientArchive).where(PatientArchive.name == rec["patient_name"])
        )
        pa = pa_r.scalar_one_or_none()
        if pa is None:
            continue
        scale = scales_by_code.get(rec["scale_code"])
        if scale is None:
            continue

        existing = await db.execute(
            select(ScaleRecord).where(
                and_(
                    ScaleRecord.scale_id == scale.id,
                    ScaleRecord.patient_archive_id == str(pa.id),
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        completed_at = None
        if rec["completed_days_ago"] is not None:
            completed_at = NOW - timedelta(days=rec["completed_days_ago"])

        record = ScaleRecord(
            scale_id=scale.id,
            patient_archive_id=str(pa.id),
            answers=rec["answers"],
            total_score=rec["total_score"],
            level=rec["level"],
            conclusion=rec["conclusion"],
            completed_at=completed_at,
        )
        db.add(record)
        print(f"    + 量表记录: {rec['patient_name']} / {rec['scale_code']}")

    await db.flush()


# ════════════════════════════════════════════════════════
# 主执行函数
# ════════════════════════════════════════════════════════

async def run_rich_seed():
    print("🌱 开始丰富演示数据 Seed...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        try:
            # 加载体质问卷（已由 seed_demo.py 写入）
            q_result = await db.execute(select(ConstitutionQuestion))
            questions = q_result.scalars().all()
            if not questions:
                print("⚠️  未找到体质问卷，请先运行 seed_demo.py")
                return

            # 加载预警规则
            r_result = await db.execute(select(AlertRule))
            rules = r_result.scalars().all()
            if not rules:
                print("⚠️  未找到预警规则，请先运行 seed_demo.py")
                return

            print(f"  ✓ 加载体质问卷 {len(questions)} 道，预警规则 {len(rules)} 条")

            archive_ids = []
            for i, p in enumerate(PATIENTS, 1):
                print(f"  [{i:02d}/{len(PATIENTS)}] 处理患者: {p['name']}")
                user = await get_or_create_user(db, p["phone"], p["name"])
                await seed_health_profile(db, user, p)
                await seed_disease_records(db, user, p)
                await seed_indicators(db, user, p)
                await seed_constitution_assessment(db, user, p["body_type"], questions)
                await seed_followup(db, user, p)
                await seed_alert_events(db, user, p, rules)
                arc = await seed_patient_archive(db, user, p)
                # 如果 arc 已存在（幂等跳过），仍需查出来用于后续
                if arc is None:
                    arc_r = await db.execute(
                        select(PatientArchive).where(PatientArchive.user_id == user.id)
                    )
                    arc = arc_r.scalar_one_or_none()
                if arc:
                    archive_ids.append(arc.id)
                    await seed_clinical_documents(db, arc, p)
                await db.flush()

            # 家庭档案
            if archive_ids:
                await seed_family_archives(db, archive_ids)

            # 量表库 & 健康评估记录
            print("  ➤ 量表库与健康评估记录...")
            await seed_scales_and_records(db)

            await db.commit()
            arc_count = await db.scalar(
                select(func.count()).select_from(PatientArchive)
            )
            scale_count = await db.scalar(select(func.count()).select_from(Scale))
            rec_count = await db.scalar(select(func.count()).select_from(ScaleRecord))
            print(f"\n✅ 丰富演示数据 Seed 完成！共 {len(PATIENTS)} 位患者，{arc_count} 份居民档案")
            print(f"   量表库：{scale_count} 个量表，{rec_count} 条健康评估记录")
            print("   每位患者包含：健康档案、慢病记录、60天指标历史、体质评估、随访计划、预警事件、居民档案")

        except Exception as e:
            await db.rollback()
            import traceback
            traceback.print_exc()
            print(f"❌ Seed 失败: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(run_rich_seed())
