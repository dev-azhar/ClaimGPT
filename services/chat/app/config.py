from __future__ import annotations
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

    # Ollama LLM settings (Llama 3.2 — free, local, no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    llm_max_tokens: int = 2048
    timeout_seconds: int = 100  # 1.5 minute

    STREAM_TIMEOUT_SECONDS: int = 1

    # LangFuse settings (for agent observability)
    LANGFUSE_SECRET_KEY : str="..."
    LANGFUSE_PUBLIC_KEY : str="..."
    LANGFUSE_BASE_URL : str="..."

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "CHAT_"}


settings = Settings()

def load_langfuse_env():
    keys = [
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_BASE_URL",
    ]
    for key in keys:
        value = getattr(settings, key, None)
        if value is not None:
            os.environ[key] = str(value)