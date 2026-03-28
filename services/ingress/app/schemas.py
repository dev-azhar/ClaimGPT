from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class DocumentOut(BaseModel):
    id: UUID
    file_name: str
    file_type: Optional[str] = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ClaimOut(BaseModel):
    id: UUID
    policy_id: Optional[str] = None
    patient_id: Optional[str] = None
    status: str
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentOut] = []

    model_config = {"from_attributes": True}


class ClaimListOut(BaseModel):
    claims: List[ClaimOut]
    total: int