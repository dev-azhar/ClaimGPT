from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class ValidationOut(BaseModel):
    id: UUID
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    passed: Optional[bool] = None
    evaluated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ValidationResultOut(BaseModel):
    claim_id: UUID
    status: str
    total_rules: int
    passed: int
    failed: int
    warnings: int
    results: List[ValidationOut] = []
