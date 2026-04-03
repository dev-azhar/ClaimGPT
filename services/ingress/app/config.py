from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # File-upload constraints
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    allowed_content_types: set[str] = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/bmp",
        "image/webp",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/msword",  # .doc
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
        "text/plain",
        "text/csv",
        "application/json",
        "text/xml",
        "application/xml",
        "text/html",
    }

    # Storage root (absolute or relative to service dir)
    storage_root: str = str(Path(__file__).resolve().parents[1] / "storage" / "raw")

    # CORS — set to your frontend origin(s) in production
    cors_origins: list[str] = ["http://localhost:3000"]

    # Workflow service URL for auto-trigger
    workflow_url: str = "http://localhost:8000/workflow"

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "INGRESS_"}


settings = Settings()
