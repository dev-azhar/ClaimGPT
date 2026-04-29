from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ParsedFieldOut(BaseModel):
    id: UUID
    field_name: str
    field_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    source_page: int | None = None
    document_id: UUID | None = None
    doc_type: str | None = None
    model_version: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ParseResultOut(BaseModel):
    claim_id: UUID
    status: str
    model_version: str | None = None
    used_fallback: bool = False
    fields: list[ParsedFieldOut] = []
    tables: list[dict[str, Any]] = []


class ParseJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    model_version: str | None = None
    used_fallback: bool = False
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ParseJobStatusOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    model_version: str | None = None
    used_fallback: bool = False
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    fields: list[ParsedFieldOut] = []
    tables: list[dict[str, Any]] = []
