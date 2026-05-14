from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SemanticSourceToken(BaseModel):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    document_id: Optional[str] = None
    claim_id: Optional[str] = None


class SemanticFieldOutput(BaseModel):
    canonical_field: str
    value: str
    confidence: float = 0.0
    source_region_id: Optional[str] = None
    source_region_type: Optional[str] = None
    source_tokens: list[SemanticSourceToken] = Field(default_factory=list)
    model_name: Optional[str] = None
    extractor_name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticTableRowOutput(BaseModel):
    row_index: int
    row_type: Optional[str] = None
    cells: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0


class SemanticTableOutput(BaseModel):
    table_kind: str
    confidence: float = 0.0
    source_region_id: Optional[str] = None
    source_region_type: Optional[str] = None
    source_tokens: list[SemanticSourceToken] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    rows: list[SemanticTableRowOutput] = Field(default_factory=list)
    model_name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticRegionOutput(BaseModel):
    region_id: str
    region_type: str
    semantic_type: str
    confidence: float = 0.0
    source_page: Optional[int] = None
    document_id: Optional[str] = None
    claim_id: Optional[str] = None
    source_tokens: list[SemanticSourceToken] = Field(default_factory=list)
    fields: list[SemanticFieldOutput] = Field(default_factory=list)
    tables: list[SemanticTableOutput] = Field(default_factory=list)
    model_name: Optional[str] = None
    notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticDocumentOutput(BaseModel):
    model_name: Optional[str] = None
    model_predictions: list[dict[str, Any]] = Field(default_factory=list)
    semantic_regions: list[SemanticRegionOutput] = Field(default_factory=list)
    semantic_fields: list[SemanticFieldOutput] = Field(default_factory=list)
    classified_tables: list[SemanticTableOutput] = Field(default_factory=list)
    semantic_field_mapping: dict[str, Any] = Field(default_factory=dict)
    semantic_table_mapping: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
