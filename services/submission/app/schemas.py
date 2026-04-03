from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SubmissionOut(BaseModel):
    submission_id: UUID
    claim_id: UUID
    payer: str | None = None
    status: str | None = None
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}


class SubmissionDetailOut(BaseModel):
    submission_id: UUID
    claim_id: UUID
    payer: str | None = None
    status: str | None = None
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}


class SubmitRequest(BaseModel):
    payer: str | None = None
