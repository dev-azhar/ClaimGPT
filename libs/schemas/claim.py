"""Canonical claim status and shared claim schemas."""

from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class ClaimStatus(str, Enum):
    """Canonical claim lifecycle statuses used across all services."""
    UPLOADED = "UPLOADED"
    OCR_PROCESSING = "OCR_PROCESSING"
    OCR_DONE = "OCR_DONE"
    OCR_FAILED = "OCR_FAILED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    PARSE_FAILED = "PARSE_FAILED"
    CODING = "CODING"
    CODED = "CODED"
    CODING_FAILED = "CODING_FAILED"
    PREDICTING = "PREDICTING"
    PREDICTED = "PREDICTED"
    PREDICT_FAILED = "PREDICT_FAILED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimEvent(BaseModel):
    """Lightweight claim reference passed between services."""
    claim_id: UUID
    status: ClaimStatus
    timestamp: datetime
    metadata: Dict[str, Any] = {}


class ParsedFieldRef(BaseModel):
    field_name: str
    field_value: Optional[str] = None


class MedicalCodeRef(BaseModel):
    code: str
    code_system: str  # ICD10 | CPT
    description: Optional[str] = None
    confidence: Optional[float] = None
    is_primary: bool = False


class PredictionRef(BaseModel):
    rejection_score: float
    top_reasons: List[Dict[str, Any]] = []
    model_name: Optional[str] = None
    model_version: Optional[str] = None


class ValidationIssue(BaseModel):
    rule_id: str
    rule_name: str
    severity: str  # INFO | WARN | ERROR
    message: str
    passed: bool
