from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class SubmissionOut(BaseModel):
    submission_id: UUID
    claim_id: UUID
    payer: Optional[str] = None
    status: Optional[str] = None
    submitted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SubmissionDetailOut(BaseModel):
    submission_id: UUID
    claim_id: UUID
    payer: Optional[str] = None
    status: Optional[str] = None
    request_payload: Optional[Dict[str, Any]] = None
    response_payload: Optional[Dict[str, Any]] = None
    submitted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SubmitRequest(BaseModel):
    payer: Optional[str] = None
