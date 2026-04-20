from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"
    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    # Vector search
    embedding_model: str = "all-MiniLM-L6-v2"
    faiss_index_path: str = "/tmp/claimgpt_faiss.index"
    faiss_id_map_path: str = "/tmp/claimgpt_faiss_ids.json"

    model_config = {"env_prefix": "SEARCH_"}


settings = Settings()
