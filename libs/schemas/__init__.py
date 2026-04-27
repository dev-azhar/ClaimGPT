"""Shared Pydantic schemas for inter-service communication."""

from .claim import ClaimEvent, ClaimStatus
from .events import (
    BaseEvent,
    ClaimIngestedEvent,
    CodingCompletedEvent,
    EventEnvelope,
    OcrCompletedEvent,
    ParseCompletedEvent,
    PipelineEvent,
    PredictCompletedEvent,
    SubmissionCompletedEvent,
    ValidationCompletedEvent,
    WorkflowCompletedEvent,
)

__all__ = [
    "ClaimEvent",
    "ClaimStatus",
    "BaseEvent",
    "EventEnvelope",
    "PipelineEvent",
    "ClaimIngestedEvent",
    "OcrCompletedEvent",
    "ParseCompletedEvent",
    "CodingCompletedEvent",
    "PredictCompletedEvent",
    "ValidationCompletedEvent",
    "SubmissionCompletedEvent",
    "WorkflowCompletedEvent",
]
