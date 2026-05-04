from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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


# ── RAG search schemas ──────────────────────────────────────────────


class CodeSearchRequest(BaseModel):
    """Request body for ICD-10 / CPT semantic search."""
    query: str = Field(..., min_length=1, max_length=500, description="Free-text clinical query")
    max_results: int = Field(5, ge=1, le=50, description="Max results to return")
    min_score: float = Field(0.25, ge=0.0, le=1.0, description="Minimum cosine similarity")


class CodeSearchHit(BaseModel):
    """A single semantic-search match."""
    code: str
    description: str
    category: str
    score: float


class CodeSearchResponse(BaseModel):
    query: str
    code_system: str  # "ICD-10" or "CPT"
    total: int
    results: list[CodeSearchHit] = []


class RagCacheStats(BaseModel):
    """Per-index LRU cache stats for ops/monitoring."""
    icd10: dict[str, int]
    cpt: dict[str, int]
