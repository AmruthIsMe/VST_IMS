from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
import os
import json


class Settings(BaseSettings):
    APP_NAME: str = "VST IMS API"
    DEBUG: bool = False

    # Database: defaults to local SQLite; override with env var for cloud PostgreSQL
    DATABASE_URL: str = f"sqlite:///{os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vst_ims.db').replace(chr(92), '/')}"

    # Deployment mode: "local" (full ML) or "cloud" (pre-computed predictions only)
    DEPLOYMENT_MODE: str = "local"

    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    ALGORITHM: str = "HS256"
    CORS_ORIGINS: list[str] = [
        "https://vst-ims.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]
    CORS_ORIGIN_REGEX: str = r"^https:\/\/.*\.vercel\.app$|^http:\/\/localhost(:\d+)?$"
    SAP_SYSNR: str = "00"
    SAP_CLIENT: str = "100"
    SAP_USER: str = ""
    SAP_PASSWORD: str = ""
    SAP_LANG: str = "EN"
    SAP_MOCK_URL: str = "http://localhost:8001"
    GEMINI_API_KEY: str = ""
    DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def parse_db_url(cls, v):
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [i.strip() for i in v.split(",")]
        return v

    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
