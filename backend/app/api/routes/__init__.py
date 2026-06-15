from fastapi import APIRouter
from app.api.routes import auth, profile, platforms, analysis, resume, health


router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(profile.router)
router.include_router(platforms.router)
router.include_router(analysis.router)
router.include_router(resume.router)
