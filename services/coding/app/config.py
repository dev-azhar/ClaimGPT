
from __future__ import annotations
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")
    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    # scispaCy model for biomedical NER
    scispacy_model: str = "en_ner_bc5cdr_md"

    # Enable UMLS entity linking (requires ~500 MB download on first use)
    use_umls_linker: bool = False

    # Enable BioGPT for code suggestion (fallback if scispaCy unavailable)
    use_biogpt: bool = True

    model_config = {"env_prefix": "CODING_"}


settings = Settings()
