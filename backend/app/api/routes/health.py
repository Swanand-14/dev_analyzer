from datetime import datetime
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "Multi-Platform Developer Analyzer API",
        "version": "4.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health")
async def health_check(request: Request):
    db_ok = False
    try:
        request.app.state.db.command("ping")
        db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "services": {
            "mongodb":    "connected"      if db_ok                          else "disconnected",
            "github_api": "configured"     if request.app.state.github       else "not configured",
            "gemini_api": "configured"     if request.app.state.gemini_flash else "not configured",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }