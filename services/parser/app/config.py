

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

    # LayoutLMv3 model — can be a local path or HuggingFace hub id
    layoutlm_model: str = "microsoft/layoutlmv3-base"

    # Fall back to heuristic parsing when model is unavailable
    use_heuristic_fallback: bool = True

    # Structured extraction via local LLM (Ollama-compatible API)
    structured_extraction_enabled: bool = True
    structured_prefer_markdown_stream: bool = True
    llm_url: str = "http://ollama:11434/api/generate"
    llm_model: str = "llama3.2"
    structured_max_chars: int = 24000
    llm_timeout_seconds: int = 180
    structured_retry_chars: int = 8000

    # Region-first semantic extraction backend order.
    # Preferred order: OpenRouter (fast hosted) -> Qwen2-VL -> LayoutLMv3 -> Florence-2 -> Donut -> local semantic LLM.
    semantic_backend_order: str = "openrouter,qwen2-vl,layoutlmv3,florence-2,donut,ollama"
    qwen2_vl_model: str = ""
    florence2_model: str = ""
    donut_model: str = ""
    semantic_llm_url: str = ""
    semantic_llm_model: str = ""
    semantic_llm_timeout_seconds: int = 120
    semantic_prompt_max_chars: int = 12000
    semantic_min_confidence: float = 0.55

    # Optional debug outputs for semantic region extraction.
    semantic_debug_enabled: bool = True

    # OpenRouter (hosted) settings - optional; useful to route to an external model
    # NOTE: Use openrouter.ai (not api.openrouter.ai) — the latter returns NXDOMAIN in many networks
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_api_key: str = "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"  # For quick testing you may place the key here (not for production)
    openrouter_model: str = "openai/gpt-4o-mini"  # default free/test model name

    # Page-level document routing + schema guards
    enable_document_router: bool = True
    enable_spatial_table_mapping: bool = True
    enable_strict_field_validation: bool = True
    prefer_vlm_codes: bool = True
    vlm_code_model_version: str = "paddleocr-vl-1.5-doc-parser"

    # Optional medical NER enrichment (scispaCy)
    enable_medical_ner: bool = False
    scispacy_model: str = "en_core_sci_lg"

    # Temporary debug dump of OCR + parsed output for inspection
    debug_dump_enabled: bool = True
    debug_dump_dir: str = "tmp/parser_debug"

    # HuggingFace cache directory (set to avoid re-downloading)
    hf_cache_dir: str = ""

    # CORS
    cors_origins: list[str] = ["*"]

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "PARSER_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
