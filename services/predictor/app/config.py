from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"
    model_name: str = "claimgpt-rejection-v1"
    model_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "PREDICTOR_"}


settings = Settings()
