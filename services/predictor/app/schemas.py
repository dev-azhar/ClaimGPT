from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class FeatureOut(BaseModel):
    claim_id: UUID
    feature_vector: Dict[str, Any]
    generated_at: datetime

    model_config = {"from_attributes": True}


class PredictionOut(BaseModel):
    id: UUID
    claim_id: UUID
    rejection_score: Optional[float] = None
    top_reasons: Optional[List[Dict[str, Any]]] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PredictResultOut(BaseModel):
    claim_id: UUID
    status: str
    prediction: Optional[PredictionOut] = None
    features: Optional[FeatureOut] = None
