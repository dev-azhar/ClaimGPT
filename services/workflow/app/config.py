# services/workflow/app/config.py — CORRECTED VERSION
# Fixes: Hardcoded localhost URLs → container DNS names

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DATABASE: Use container DNS "postgres" instead of localhost
    database_url: str = "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt"

    # DOWNSTREAM SERVICE URLs: Use container DNS names instead of localhost
    # These resolve via Docker's embedded DNS within the container network
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

    # CORS: Allow frontend on production domain
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "WORKFLOW_"}


settings = Settings()
