"""API version 1. Evolution inside a version is additive-only by contract."""

from fastapi import APIRouter

from spidey.api.v1.auth import router as auth_router
from spidey.api.v1.health import router as health_router
from spidey.api.v1.runs import router as runs_router
from spidey.api.v1.sessions import router as sessions_router
from spidey.api.v1.users import router as users_router
from spidey.api.v1.workspaces import router as workspaces_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(sessions_router)
router.include_router(workspaces_router)
router.include_router(runs_router)
