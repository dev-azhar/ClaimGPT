
from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")
    model_name: str = "claimgpt-rejection-v1"
    model_version: str = "0.1.0"
    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "PREDICTOR_"}


settings = Settings()
