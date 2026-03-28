from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # LayoutLMv3 model — can be a local path or HuggingFace hub id
    layoutlm_model: str = "microsoft/layoutlmv3-base"

    # Fall back to heuristic parsing when model is unavailable
    use_heuristic_fallback: bool = True

    # HuggingFace cache directory (set to avoid re-downloading)
    hf_cache_dir: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "PARSER_"}


settings = Settings()
