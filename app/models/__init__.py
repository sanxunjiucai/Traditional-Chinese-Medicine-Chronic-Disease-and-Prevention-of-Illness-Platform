# Import all models so Alembic can detect them via Base.metadata
from app.models.enums import (  # noqa: F401
    AlertSeverity,
    AlertStatus,
    AssessmentStatus,
    BodyType,
    CheckInStatus,
    ContentStatus,
    DiseaseType,
    FollowupStatus,
    IndicatorType,
    PlanStatus,
    RecommendationCategory,
    TaskType,
    UserRole,
)
from app.models.user import ConsentRecord, FamilyMember, User  # noqa: F401
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile  # noqa: F401
from app.models.constitution import (  # noqa: F401
    ConstitutionAnswer,
    ConstitutionAssessment,
    ConstitutionQuestion,
)
from app.models.recommendation import RecommendationPlan, RecommendationTemplate  # noqa: F401
from app.models.followup import CheckIn, FollowupPlan, FollowupTask, FollowupTemplate  # noqa: F401
from app.models.alert import AlertEvent, AlertRule  # noqa: F401
from app.models.content import ContentItem  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
