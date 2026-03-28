from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class MedicalCodeOut(BaseModel):
    id: UUID
    code: str
    code_system: str
    description: Optional[str] = None
    confidence: Optional[float] = None
    is_primary: bool = False
    estimated_cost: Optional[float] = None

    model_config = {"from_attributes": True}


class MedicalEntityOut(BaseModel):
    id: UUID
    entity_text: str
    entity_type: str
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    confidence: Optional[float] = None
    codes: List[MedicalCodeOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class CodingResultOut(BaseModel):
    claim_id: UUID
    status: str
    entities: List[MedicalEntityOut] = []
    icd_codes: List[MedicalCodeOut] = []
    cpt_codes: List[MedicalCodeOut] = []
