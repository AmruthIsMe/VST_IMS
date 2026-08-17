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

    SECRET_KEY: str = "vst-ims-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    SAP_HOST: str = ""
    SAP_SYSNR: str = "00"
    SAP_CLIENT: str = "100"
    SAP_USER: str = ""
    SAP_PASSWORD: str = ""
    SAP_LANG: str = "EN"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [i.strip() for i in v.split(",")]
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
