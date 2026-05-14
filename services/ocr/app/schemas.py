from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OcrPageOut(BaseModel):
    id: UUID
    page_number: int | None = None
    text: str | None = None
    confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OcrDocumentOut(BaseModel):
    document_id: UUID
    file_name: str
    pages: list[OcrPageOut]
    total_pages: int


class OcrJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class OcrJobStatusOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    status: str
    total_documents: int
    processed_documents: int
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    results: list[OcrDocumentOut] = []


# ── Document validation schemas ──

class PatientIdentityOut(BaseModel):
    name: str | None = None
    patient_id: str | None = None
    dob: str | None = None
    age: str | None = None
    gender: str | None = None
    policy_number: str | None = None


class DocValidationOut(BaseModel):
    document_id: UUID
    file_name: str
    status: str
    doc_type: str | None = None
    doc_type_label: str | None = None
    is_medical: bool
    patient_match: str | None = None
    confidence: float | None = None
    issues: list[str] = []
    patient_identity: PatientIdentityOut | None = None


class ClaimValidationOut(BaseModel):
    claim_id: UUID
    status: str
    total_documents: int
    valid_count: int
    invalid_count: int
    warning_count: int
    primary_patient: PatientIdentityOut | None = None
    documents: list[DocValidationOut] = []
    issues: list[str] = []
