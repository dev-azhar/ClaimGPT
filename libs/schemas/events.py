"""
Async event schemas for inter-service messaging (Kafka / Redis Streams).

Each service publishes events after completing its pipeline step.
The workflow orchestrator (or any subscriber) consumes these events.

Design
------
* **BaseEvent** — common envelope fields shared by every event (id, timestamp,
  source, correlation).  Individual events inherit from it and pin
  ``event_type`` to a ``Literal`` so Pydantic can discriminate on deserialise.
* **EventEnvelope** — a typed wrapper that holds *any* pipeline event in its
  ``payload`` field via a discriminated union, preserving full type safety.
* **correlation_id** — links every event in the same claim-processing chain so
  distributed traces can be reconstructed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Base ────────────────────────────────────────────────────────────

class BaseEvent(BaseModel):
    """Fields common to every pipeline event."""
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_service: str = ""
    correlation_id: UUID | None = None


# ── Pipeline events ─────────────────────────────────────────────────

class ClaimIngestedEvent(BaseEvent):
    """Published by ingress when a new claim is uploaded."""
    event_type: Literal["claim.ingested"] = "claim.ingested"
    source_service: str = "ingress"
    claim_id: UUID
    document_ids: list[UUID] = []
    policy_id: str | None = None
    patient_id: str | None = None


class OcrCompletedEvent(BaseEvent):
    """Published by OCR service when job completes."""
    event_type: Literal["ocr.completed"] = "ocr.completed"
    source_service: str = "ocr"
    claim_id: UUID
    job_id: UUID
    status: str  # COMPLETED | FAILED
    total_pages: int = 0
    error_detail: str | None = None


class ParseCompletedEvent(BaseEvent):
    """Published by parser when field extraction finishes."""
    event_type: Literal["parse.completed"] = "parse.completed"
    source_service: str = "parser"
    claim_id: UUID
    job_id: UUID
    status: str
    num_fields: int = 0
    used_fallback: bool = False
    error_detail: str | None = None


class CodingCompletedEvent(BaseEvent):
    """Published by coding service after NER + code assignment."""
    event_type: Literal["coding.completed"] = "coding.completed"
    source_service: str = "coding"
    claim_id: UUID
    num_entities: int = 0
    num_codes: int = 0


class PredictCompletedEvent(BaseEvent):
    """Published by predictor after scoring."""
    event_type: Literal["predict.completed"] = "predict.completed"
    source_service: str = "predictor"
    claim_id: UUID
    rejection_score: float
    model_name: str | None = None


class ValidationCompletedEvent(BaseEvent):
    """Published by validator after rule evaluation."""
    event_type: Literal["validation.completed"] = "validation.completed"
    source_service: str = "validator"
    claim_id: UUID
    valid: bool
    error_count: int = 0
    warning_count: int = 0


class SubmissionCompletedEvent(BaseEvent):
    """Published by submission service after payer submission."""
    event_type: Literal["submission.completed"] = "submission.completed"
    source_service: str = "submission"
    claim_id: UUID
    submission_id: UUID
    payer: str
    status: str


class WorkflowCompletedEvent(BaseEvent):
    """Published by workflow orchestrator when the full pipeline finishes."""
    event_type: Literal["workflow.completed"] = "workflow.completed"
    source_service: str = "workflow"
    claim_id: UUID
    success: bool
    failed_step: str | None = None
    total_processing_seconds: float | None = None
    error_detail: str | None = None


# ── Discriminated union ─────────────────────────────────────────────

PipelineEvent = Annotated[
    Union[
        ClaimIngestedEvent,
        OcrCompletedEvent,
        ParseCompletedEvent,
        CodingCompletedEvent,
        PredictCompletedEvent,
        ValidationCompletedEvent,
        SubmissionCompletedEvent,
        WorkflowCompletedEvent,
    ],
    Field(discriminator="event_type"),
]


# ── Envelope ────────────────────────────────────────────────────────

class EventEnvelope(BaseModel):
    """
    Standard wrapper for publishing / consuming events on the message bus.

    ``payload`` is a discriminated union — Pydantic will automatically
    deserialise it to the correct concrete event class based on
    ``event_type``.
    """
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    source_service: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str | None = None
    correlation_id: UUID | None = None
    payload: dict[str, Any] | PipelineEvent = Field(default_factory=dict)

    @classmethod
    def wrap(cls, event: PipelineEvent, *, idempotency_key: str | None = None) -> EventEnvelope:
        """Create an envelope around a typed pipeline event."""
        return cls(
            event_type=getattr(event, "event_type", type(event).__name__),
            source_service=event.source_service,
            correlation_id=event.correlation_id,
            idempotency_key=idempotency_key,
            payload=event,
        )
