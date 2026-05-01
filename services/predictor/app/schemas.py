from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class FeatureOut(BaseModel):
    claim_id: UUID
    feature_vector: dict[str, Any]
    generated_at: datetime

    model_config = {"from_attributes": True}


class PredictionOut(BaseModel):
    id: UUID
    claim_id: UUID
    rejection_score: float | None = None
    risk_category: str | None = None
    top_reasons: list[dict[str, Any]] | None = None
    model_name: str | None = None
    model_version: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PredictResultOut(BaseModel):
    claim_id: UUID
    status: str
    prediction: PredictionOut | None = None
    features: FeatureOut | None = None
