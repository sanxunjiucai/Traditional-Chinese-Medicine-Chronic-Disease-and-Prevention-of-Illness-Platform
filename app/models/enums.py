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
