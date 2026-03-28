from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class SearchHit(BaseModel):
    claim_id: UUID
    score: float
    highlights: List[str] = []
    status: Optional[str] = None
    policy_id: Optional[str] = None
    created_at: Optional[datetime] = None


class SearchResultOut(BaseModel):
    query: str
    total: int
    results: List[SearchHit] = []


class VectorSearchRequest(BaseModel):
    text: str
    top_k: int = 10


class IndexRequest(BaseModel):
    claim_ids: List[UUID]
