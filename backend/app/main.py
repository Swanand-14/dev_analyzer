from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.middleware import add_middleware
from app.api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting up...")
 
    from app.db.mongo import connect_db
    app.state.db = connect_db()
    print("✅ MongoDB ready")
 
    from app.core.config import get_settings
    from github import Github
    settings = get_settings()
    app.state.github = Github(settings.GITHUB_TOKEN) if settings.GITHUB_TOKEN else None
    print("✅ GitHub client ready" if app.state.github else "⚠️  GitHub token not set")
 
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    app.state.gemini_flash_lite = genai.GenerativeModel("gemini-2.5-flash-lite")
    app.state.gemini_flash      = genai.GenerativeModel("gemini-2.5-flash")
    print("✅ Gemini models ready")
 
    yield  # server live
 
    # ── SHUTDOWN ─────────────────────────────────────────────
    print("🛑 Shutting down...")
    from app.db.mongo import disconnect_db
    disconnect_db()
    print("✅ MongoDB disconnected")

app = FastAPI(
    title="Multi-Platform Developer Analyzer API",
    description="AI-powered analysis for GitHub, LeetCode, and Codeforces",
    version="4.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

add_middleware(app)
app.include_router(router)