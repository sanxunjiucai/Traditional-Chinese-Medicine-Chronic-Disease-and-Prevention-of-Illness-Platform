from fastapi import APIRouter

from app.tools.auth_tools import router as auth_router
from app.tools.health_tools import router as health_router
from app.tools.constitution_tools import router as constitution_router
from app.tools.followup_tools import router as followup_router
from app.tools.alert_tools import router as alert_router
from app.tools.content_tools import router as content_router
from app.tools.audit_tools import router as audit_router
from app.tools.admin_tools import router as admin_router
from app.tools.agent_tools import router as agent_router
from app.tools.assistant_tools import router as assistant_router
from app.tools.guidance_tools import router as guidance_router
from app.tools.mgmt_tools import router as mgmt_router
from app.tools.archive_tools import router as archive_router
from app.tools.clinical_tools import router as clinical_router
from app.tools.sysdict_tools import router as sysdict_router
from app.tools.intervention_tools import router as intervention_router
from app.tools.education_tools import router as education_router
from app.tools.scale_tools import router as scale_router
from app.tools.followup_rule_tools import router as followup_rule_router
from app.tools.label_tools import router as label_router
from app.tools.risk_tools import router as risk_router
from app.tools.notification_tools import router as notification_router
from app.tools.consultation_tools import router as consultation_router
from app.tools.business_stats_tools import router as business_stats_router
from app.tools.activity_tools import router as activity_router
from app.tools.plugin_tools import router as plugin_router
from app.tools.preventive_tools import router as preventive_router

router = APIRouter(prefix="/tools")
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(constitution_router)
router.include_router(followup_router)
router.include_router(alert_router)
router.include_router(content_router)
router.include_router(audit_router)
router.include_router(admin_router)
router.include_router(agent_router)
router.include_router(assistant_router)
router.include_router(guidance_router)
router.include_router(mgmt_router)
router.include_router(archive_router)
router.include_router(clinical_router)
router.include_router(sysdict_router)
router.include_router(intervention_router)
router.include_router(education_router)
router.include_router(scale_router)
router.include_router(followup_rule_router)
router.include_router(label_router)
router.include_router(risk_router)
router.include_router(notification_router)
router.include_router(consultation_router)
router.include_router(business_stats_router)
router.include_router(activity_router)
router.include_router(plugin_router)
router.include_router(preventive_router)
