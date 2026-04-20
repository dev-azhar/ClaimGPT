
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
