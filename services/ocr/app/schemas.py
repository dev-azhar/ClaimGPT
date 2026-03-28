from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class OcrPageOut(BaseModel):
    id: UUID
    page_number: Optional[int] = None
    text: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OcrDocumentOut(BaseModel):
    document_id: UUID
    file_name: str
    pages: List[OcrPageOut]
    total_pages: int


class OcrJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OcrJobStatusOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    results: List[OcrDocumentOut] = []
