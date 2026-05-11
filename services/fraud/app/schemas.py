from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FraudIndicator(BaseModel):
    code: str                 # e.g. R-DUP-01
    name: str                 # human-readable
    layer: str                # rules / ml / llm
    severity: str             # INFO / WARN / HIGH
    weight: float             # contribution to component score [0,1]
    message: str
    evidence: dict | None = None


class FraudAssessmentOut(BaseModel):
    id: UUID | None = None
    claim_id: UUID
    fraud_score: float            # blended [0.0, 1.0]
    fraud_category: str           # LOW / MEDIUM / HIGH
    rules_score: float | None = None
    ml_score: float | None = None
    llm_score: float | None = None
    indicators: list[FraudIndicator] = []
    model_name: str | None = None
    model_version: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class FraudResultOut(BaseModel):
    claim_id: UUID
    status: str
    assessment: FraudAssessmentOut | None = None
