from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SearchHit(BaseModel):
    claim_id: UUID
    score: float
    highlights: list[str] = []
    status: str | None = None
    policy_id: str | None = None
    created_at: datetime | None = None


class SearchResultOut(BaseModel):
    query: str
    total: int
    results: list[SearchHit] = []


class VectorSearchRequest(BaseModel):
    text: str
    top_k: int = 10


class IndexRequest(BaseModel):
    claim_ids: list[UUID]
