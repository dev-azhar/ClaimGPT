from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Detector toggles — operators can disable any layer in production.
    rules_enabled: bool = True
    ml_enabled: bool = True
    llm_enabled: bool = False  # off by default; requires local_llm

    # Hybrid score weights (must sum to ~1.0)
    weight_rules: float = 0.5
    weight_ml: float = 0.4
    weight_llm: float = 0.1

    # Risk thresholds (final blended score → category)
    threshold_high: float = 0.70
    threshold_medium: float = 0.40

    # Velocity / duplicate detection windows
    velocity_window_days: int = 30
    velocity_max_claims: int = 5  # > N claims for same patient/policy in window → suspicious
    duplicate_lookback_days: int = 90

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "FRAUD_"}


settings = Settings()
