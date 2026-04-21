from __future__ import annotations

from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Ollama LLM settings (Llama 3.2 — free, local, no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    llm_max_tokens: int = 2048
    timeout_seconds: int = 90  # 1.5 minute

    STREAM_TIMEOUT_SECONDS: int = 1

    # LangFuse settings (for agent observability)
    LANGFUSE_SECRET_KEY : str="..."
    LANGFUSE_PUBLIC_KEY : str="..."
    LANGFUSE_BASE_URL : str="..."

    cors_origins: list[str] = ["http://localhost:3000"]
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