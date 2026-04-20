

from __future__ import annotations
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

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
    cors_origins: list[str] = ["*"]

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "OCR_"}


settings = Settings()
