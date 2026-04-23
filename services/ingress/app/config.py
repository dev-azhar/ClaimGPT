

from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")

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

    # Storage root (absolute or relative to service dir).
    # Default points to the in-repo path so local dev works without env vars;
    # override with INGRESS_STORAGE_ROOT in containerised deployments.
    storage_root: str = os.environ.get(
        "INGRESS_STORAGE_ROOT",
        str(Path(__file__).resolve().parents[1] / "storage" / "raw"),
    )

    # CORS — set to your frontend origin(s) in production
    cors_origins: list[str] = ["*"]

    # Workflow service URL for auto-trigger
    workflow_url: str = "http://gateway:8000/workflow"

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "INGRESS_"}


settings = Settings()
