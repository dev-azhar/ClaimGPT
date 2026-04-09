from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Tesseract binary path (override if non-standard)
    tesseract_cmd: str = "tesseract"

    # OCR backend controls
    enable_paddle_ocr: bool = True
    enable_paddle_vl: bool = False
    paddle_language: str = "en"
    paddle_vl_doc_parser: bool = True
    paddle_vl_merge_cross_page_tables: bool = True
    enable_secondary_ocr_on_pdf: bool = True

    # Temporary debug dump for OCR page objects
    debug_dump_enabled: bool = True
    debug_dump_dir: str = "tmp/ocr_debug"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "OCR_"}


settings = Settings()
