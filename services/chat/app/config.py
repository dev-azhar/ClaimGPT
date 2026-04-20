
from __future__ import annotations
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

    # Ollama LLM settings (Llama 3.2 — free, local, no API key)
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2"
    llm_max_tokens: int = 2048

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "CHAT_"}


settings = Settings()
