"""API version 1. Evolution inside a version is additive-only by contract."""

from fastapi import APIRouter

from spidey.api.v1.health import router as health_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
