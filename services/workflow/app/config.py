from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

    # Downstream service URLs (unified gateway)
    ocr_url: str = "http://ocr:8000"
    parser_url: str = "http://parser:8000"
    coding_url: str = "http://coding:8000"
    predictor_url: str = "http://predictor:8000"
    validator_url: str = "http://validator:8000"
    submission_url: str = "http://submission:8000"

    max_retries: int = 3
    retry_backoff: float = 2.0  # seconds
    async_poll_max_seconds: int = 1200
    async_poll_interval_seconds: int = 5

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "WORKFLOW_"}


settings = Settings()
