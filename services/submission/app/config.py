from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Default payer adapter
    default_payer: str = "generic"

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "SUBMISSION_"}


settings = Settings()
