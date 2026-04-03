from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ValidationOut(BaseModel):
    id: UUID
    rule_id: str | None = None
    rule_name: str | None = None
    severity: str | None = None
    message: str | None = None
    passed: bool | None = None
    evaluated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ValidationResultOut(BaseModel):
    claim_id: UUID
    status: str
    total_rules: int
    passed: int
    failed: int
    warnings: int
    results: list[ValidationOut] = []
