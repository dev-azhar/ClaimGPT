from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # LayoutLMv3 model — can be a local path or HuggingFace hub id
    layoutlm_model: str = "microsoft/layoutlmv3-base"

    # Fall back to heuristic parsing when model is unavailable
    use_heuristic_fallback: bool = True

    # Structured extraction via local LLM (Ollama-compatible API)
    structured_extraction_enabled: bool = True
    structured_prefer_markdown_stream: bool = True
    llm_url: str = "http://localhost:11434/api/generate"
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
    cors_origins: list[str] = ["http://localhost:3000"]

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "PARSER_"}


settings = Settings()
