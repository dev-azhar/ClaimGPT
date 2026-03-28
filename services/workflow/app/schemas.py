from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class WorkflowJobOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    job_type: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None
    retries: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WorkflowStepStatus(BaseModel):
    step: str
    status: str  # PENDING / RUNNING / DONE / FAILED / SKIPPED
    detail: Optional[str] = None


class WorkflowDetailOut(BaseModel):
    job_id: UUID
    claim_id: UUID
    job_type: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None
    steps: List[WorkflowStepStatus] = []
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
