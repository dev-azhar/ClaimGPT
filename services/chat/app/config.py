from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # LLM provider: "groq" | "gemini" | "anthropic" | "openai" | "ollama" | "huggingface" | "openai_compat"
    #   groq         — Groq Cloud (Llama 3.3 70B, Mixtral) — fastest, free tier
    #   gemini       — Google Gemini (gemini-2.0-flash) — free tier available
    #   anthropic    — Anthropic Claude (claude-3.5-sonnet) — best reasoning
    #   openai       — OpenAI API (GPT-4o etc.)
    #   ollama       — local Ollama server (meditron, medllama2, llama3)
    #   huggingface  — local BioMistral / MedAlpaca via transformers
    #   openai_compat — any OpenAI-compatible endpoint (vLLM, LM Studio)
    llm_provider: str = "ollama"

    # Groq settings (free tier: 30 req/min, Llama 3.3 70B)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Google Gemini settings
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Anthropic Claude settings
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # HuggingFace settings
    hf_model_name: str = "microsoft/biogpt"
    hf_device: str = "cpu"
    hf_max_new_tokens: int = 512
    hf_load_in_4bit: bool = False

    # Ollama settings (Llama 3.2 — free, local, no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # OpenAI settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # OpenAI-compatible (vLLM, LM Studio, etc.)
    llm_base_url: str = "http://localhost:8080/v1"
    llm_model: str = "claimgpt-chat"
    llm_max_tokens: int = 2048

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    model_config = {"env_prefix": "CHAT_"}


settings = Settings()
