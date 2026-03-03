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

from sqlalchemy import select
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
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile
from app.models.user import User
from app.services.auth_service import hash_password

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

            for i, p in enumerate(PATIENTS, 1):
                print(f"  [{i:02d}/{len(PATIENTS)}] 处理患者: {p['name']}")
                user = await get_or_create_user(db, p["phone"], p["name"])
                await seed_health_profile(db, user, p)
                await seed_disease_records(db, user, p)
                await seed_indicators(db, user, p)
                await seed_constitution_assessment(db, user, p["body_type"], questions)
                await seed_followup(db, user, p)
                await seed_alert_events(db, user, p, rules)
                await db.flush()

            await db.commit()
            print(f"\n✅ 丰富演示数据 Seed 完成！共创建 {len(PATIENTS)} 位患者")
            print("   每位患者包含：健康档案、慢病记录、60天指标历史、体质评估、随访计划、预警事件")

        except Exception as e:
            await db.rollback()
            import traceback
            traceback.print_exc()
            print(f"❌ Seed 失败: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(run_rich_seed())
