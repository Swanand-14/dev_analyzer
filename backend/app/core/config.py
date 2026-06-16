from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Server
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    
    # Dev
    DEV_MODE: bool = False

    # Database
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "github"

    # External APIs
    GITHUB_TOKEN: str = ""
    GEMINI_API_KEY: str = ""

    # Auth (Clerk)
    CLERK_JWKS_URL: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()