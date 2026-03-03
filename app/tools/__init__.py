from fastapi import APIRouter

from app.tools.auth_tools import router as auth_router
from app.tools.health_tools import router as health_router
from app.tools.constitution_tools import router as constitution_router
from app.tools.followup_tools import router as followup_router
from app.tools.alert_tools import router as alert_router
from app.tools.content_tools import router as content_router
from app.tools.audit_tools import router as audit_router

router = APIRouter(prefix="/tools")
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(constitution_router)
router.include_router(followup_router)
router.include_router(alert_router)
router.include_router(content_router)
router.include_router(audit_router)
