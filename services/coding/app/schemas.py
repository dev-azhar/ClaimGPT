from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MedicalCodeOut(BaseModel):
    id: UUID
    code: str
    code_system: str
    description: str | None = None
    confidence: float | None = None
    is_primary: bool = False
    estimated_cost: float | None = None

    model_config = {"from_attributes": True}


class MedicalEntityOut(BaseModel):
    id: UUID
    entity_text: str
    entity_type: str
    start_offset: int | None = None
    end_offset: int | None = None
    confidence: float | None = None
    codes: list[MedicalCodeOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class CodingResultOut(BaseModel):
    claim_id: UUID
    status: str
    entities: list[MedicalEntityOut] = []
    icd_codes: list[MedicalCodeOut] = []
    cpt_codes: list[MedicalCodeOut] = []
