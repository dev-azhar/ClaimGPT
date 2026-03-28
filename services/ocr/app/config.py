from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Tesseract binary path (override if non-standard)
    tesseract_cmd: str = "tesseract"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "OCR_"}


settings = Settings()
