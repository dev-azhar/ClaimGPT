from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class ParsedFieldOut(BaseModel):
    id: UUID
    field_name: str
    field_value: Optional[str] = None
    bounding_box: Optional[Dict[str, Any]] = None
    source_page: Optional[int] = None
    model_version: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ParseResultOut(BaseModel):
    claim_id: UUID
    status: str
    model_version: Optional[str] = None
    used_fallback: bool = False
    fields: List[ParsedFieldOut] = []
    tables: List[Dict[str, Any]] = []


class ParseJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    model_version: Optional[str] = None
    used_fallback: bool = False
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ParseJobStatusOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    model_version: Optional[str] = None
    used_fallback: bool = False
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    fields: List[ParsedFieldOut] = []
    tables: List[Dict[str, Any]] = []
