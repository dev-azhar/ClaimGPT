from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Ollama LLM settings (Llama 3.2 — free, local, no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    llm_max_tokens: int = 2048

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "CHAT_"}


settings = Settings()
