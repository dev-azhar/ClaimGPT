from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Downstream service URLs (unified gateway)
    ocr_url: str = "http://localhost:8000/ocr"
    parser_url: str = "http://localhost:8000/parser"
    coding_url: str = "http://localhost:8000/coding"
    predictor_url: str = "http://localhost:8000/predictor"
    validator_url: str = "http://localhost:8000/validator"
    submission_url: str = "http://localhost:8000/submission"

    max_retries: int = 3
    retry_backoff: float = 2.0  # seconds
    async_poll_max_seconds: int = 1200
    async_poll_interval_seconds: int = 5

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "WORKFLOW_"}


settings = Settings()
