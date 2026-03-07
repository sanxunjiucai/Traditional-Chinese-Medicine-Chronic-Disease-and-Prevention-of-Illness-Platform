import enum


class UserRole(str, enum.Enum):
    PATIENT = "PATIENT"
    PROFESSIONAL = "PROFESSIONAL"
    ADMIN = "ADMIN"


class DiseaseType(str, enum.Enum):
    HYPERTENSION = "HYPERTENSION"
    DIABETES_T2 = "DIABETES_T2"


class IndicatorType(str, enum.Enum):
    BLOOD_PRESSURE = "BLOOD_PRESSURE"
    BLOOD_GLUCOSE = "BLOOD_GLUCOSE"
    WEIGHT = "WEIGHT"
    WAIST_CIRCUMFERENCE = "WAIST_CIRCUMFERENCE"


class BodyType(str, enum.Enum):
    BALANCED = "BALANCED"
    QI_DEFICIENCY = "QI_DEFICIENCY"
    YANG_DEFICIENCY = "YANG_DEFICIENCY"
    YIN_DEFICIENCY = "YIN_DEFICIENCY"
    PHLEGM_DAMPNESS = "PHLEGM_DAMPNESS"
    DAMP_HEAT = "DAMP_HEAT"
    BLOOD_STASIS = "BLOOD_STASIS"
    QI_STAGNATION = "QI_STAGNATION"
    SPECIAL_DIATHESIS = "SPECIAL_DIATHESIS"


class AssessmentStatus(str, enum.Enum):
    ANSWERING = "ANSWERING"
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    REPORTED = "REPORTED"


class PlanStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVISED = "REVISED"
    ARCHIVED = "ARCHIVED"


class FollowupStatus(str, enum.Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class CheckInStatus(str, enum.Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    MISSED = "MISSED"


class AlertSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    CLOSED = "CLOSED"


class ContentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    OFFLINE = "OFFLINE"


class TaskType(str, enum.Enum):
    INDICATOR_REPORT = "INDICATOR_REPORT"
    EXERCISE = "EXERCISE"
    MEDICATION = "MEDICATION"
    SLEEP = "SLEEP"
    DIET = "DIET"


class RecommendationCategory(str, enum.Enum):
    DAILY_ROUTINE = "DAILY_ROUTINE"    # 起居作息
    DIET = "DIET"                       # 饮食调护
    EXERCISE = "EXERCISE"               # 运动导引
    EMOTIONAL = "EMOTIONAL"             # 情志调护
    EXTERNAL = "EXTERNAL"               # 外治非药


# ── 中医指导/干预/宣教 ──
class GuidanceType(str, enum.Enum):
    GUIDANCE = "GUIDANCE"          # 中医指导
    INTERVENTION = "INTERVENTION"  # 中医干预
    EDUCATION = "EDUCATION"        # 中医宣教


class TemplateScope(str, enum.Enum):
    PUBLIC = "PUBLIC"          # 公开模板
    DEPARTMENT = "DEPARTMENT"  # 科室模板
    PERSONAL = "PERSONAL"      # 个人模板
    GROUP = "GROUP"            # 组织/团队模板（兼容旧数据）


class GuidanceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"      # 医生已确认，待分发
    DISTRIBUTED = "DISTRIBUTED"  # 已分发三端
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


# ── 机构管理 ──
class OrgLevel(str, enum.Enum):
    HOSPITAL = "HOSPITAL"    # 医院/集团（1级）
    BRANCH = "BRANCH"        # 院区/分院（2级）
    CENTER = "CENTER"        # 科室/中心（3级）


# ── 定时任务 ──
class ScheduledTaskStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


# ── 档案管理 ──
class ArchiveType(str, enum.Enum):
    NORMAL = "NORMAL"        # 普通居民
    CHILD = "CHILD"          # 0-6岁儿童
    FEMALE = "FEMALE"        # 女性
    ELDERLY = "ELDERLY"      # 老年人(60+)
    KEY_FOCUS = "KEY_FOCUS"  # 重点关注人群


class IdType(str, enum.Enum):
    ID_CARD = "ID_CARD"       # 居民身份证
    PASSPORT = "PASSPORT"     # 护照
    MILITARY = "MILITARY"     # 军官证
    BIRTH_CERT = "BIRTH_CERT" # 出生医学证明
    OTHER = "OTHER"           # 其他


# ── 就诊/临床数据 ──
class DocumentType(str, enum.Enum):
    ENCOUNTER = "ENCOUNTER"          # 就诊记录
    OP_EMR = "OP_EMR"                # 门诊病历
    IP_EMR = "IP_EMR"                # 住院病历
    PRESCRIPTION = "PRESCRIPTION"    # 处方记录
    TREATMENT = "TREATMENT"          # 治疗记录
    LAB_REPORT = "LAB_REPORT"        # 检验报告
    IMAGE_REPORT = "IMAGE_REPORT"    # 影像报告
    DEVICE_REPORT = "DEVICE_REPORT"  # 设备报告


# ── 数据字典 ──
class DictStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ── 治未病·预防保健方案 ──
class PreventivePlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"                    # 草稿（医生编辑中）
    CONFIRMED = "CONFIRMED"            # 已确认（医生确认，版本锁定）
    DISTRIBUTED = "DISTRIBUTED"        # 已分发（推送到渠道）
    IN_PROGRESS = "IN_PROGRESS"        # 执行中（患者已接收）
    COMPLETED = "COMPLETED"            # 已完成
    ARCHIVED = "ARCHIVED"              # 已归档（被新版本替代）


class DistributionChannel(str, enum.Enum):
    HIS = "HIS"      # 医院信息系统
    H5 = "H5"        # 患者 H5 端
    ADMIN = "ADMIN"  # 管理后台归因


class DistributionStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IntentType(str, enum.Enum):
    APPOINTMENT = "APPOINTMENT"          # 预约就诊
    INTENT_CALLBACK = "INTENT_CALLBACK"  # 意向回电


class IntentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DONE = "DONE"
    CANCELED = "CANCELED"


class LifestyleSource(str, enum.Enum):
    DIALOGUE = "DIALOGUE"        # 从对话中提取
    QUESTIONNAIRE = "QUESTIONNAIRE"  # 问卷填写
    MANUAL = "MANUAL"            # 手动录入
    HIS_SYNC = "HIS_SYNC"        # HIS 同步


class PreventiveTaskType(str, enum.Enum):
    CHECKIN = "CHECKIN"                    # 每日打卡
    ADHERENCE = "ADHERENCE"                # 依从性评估
    EFFECT_FEEDBACK = "EFFECT_FEEDBACK"    # 效果反馈
    RETURN_VISIT = "RETURN_VISIT"          # 复诊


class PreventiveTaskStatus(str, enum.Enum):
    TODO = "TODO"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
