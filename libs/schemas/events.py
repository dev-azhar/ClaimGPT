"""
Async event schemas for inter-service messaging (Kafka / Redis Streams).

Each service publishes events after completing its pipeline step.
The workflow orchestrator (or any subscriber) consumes these events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """Standard wrapper for all async events."""
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    source_service: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str | None = None
    payload: dict[str, Any] = {}


class ClaimIngestedEvent(BaseModel):
    """Published by ingress when a new claim is uploaded."""
    event_type: str = "claim.ingested"
    claim_id: UUID
    document_ids: list[UUID] = []
    policy_id: str | None = None
    patient_id: str | None = None


class OcrCompletedEvent(BaseModel):
    """Published by OCR service when job completes."""
    event_type: str = "ocr.completed"
    claim_id: UUID
    job_id: UUID
    status: str  # COMPLETED | FAILED
    total_pages: int = 0


class ParseCompletedEvent(BaseModel):
    """Published by parser when field extraction finishes."""
    event_type: str = "parse.completed"
    claim_id: UUID
    job_id: UUID
    status: str
    num_fields: int = 0
    used_fallback: bool = False


class CodingCompletedEvent(BaseModel):
    """Published by coding service after NER + code assignment."""
    event_type: str = "coding.completed"
    claim_id: UUID
    num_entities: int = 0
    num_codes: int = 0


class PredictCompletedEvent(BaseModel):
    """Published by predictor after scoring."""
    event_type: str = "predict.completed"
    claim_id: UUID
    rejection_score: float
    model_name: str | None = None


class ValidationCompletedEvent(BaseModel):
    """Published by validator after rule evaluation."""
    event_type: str = "validation.completed"
    claim_id: UUID
    valid: bool
    error_count: int = 0
    warning_count: int = 0


class SubmissionCompletedEvent(BaseModel):
    """Published by submission service after payer submission."""
    event_type: str = "submission.completed"
    claim_id: UUID
    submission_id: UUID
    payer: str
    status: str
