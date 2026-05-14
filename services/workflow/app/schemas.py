from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WorkflowJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    job_type: str | None = None
    status: str | None = None
    current_step: str | None = None
    retries: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowStepStatus(BaseModel):
    step: str
    status: str  # PENDING / RUNNING / DONE / FAILED / SKIPPED
    detail: str | None = None


class WorkflowDetailOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    job_type: str | None = None
    status: str | None = None
    current_step: str | None = None
    steps: list[WorkflowStepStatus] = []
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
