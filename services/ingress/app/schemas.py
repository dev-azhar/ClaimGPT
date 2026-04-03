from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: UUID
    file_name: str
    file_type: str | None = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ClaimOut(BaseModel):
    id: UUID
    policy_id: str | None = None
    patient_id: str | None = None
    status: str
    source: str | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentOut] = []

    model_config = {"from_attributes": True}


class ClaimListOut(BaseModel):
    claims: list[ClaimOut]
    total: int
