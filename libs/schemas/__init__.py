"""Shared Pydantic schemas for inter-service communication."""

from .claim import ClaimEvent, ClaimStatus
from .events import (
    ClaimIngestedEvent,
    CodingCompletedEvent,
    EventEnvelope,
    OcrCompletedEvent,
    ParseCompletedEvent,
    PredictCompletedEvent,
    SubmissionCompletedEvent,
    ValidationCompletedEvent,
)

__all__ = [
    "ClaimEvent",
    "ClaimStatus",
    "EventEnvelope",
    "ClaimIngestedEvent",
    "OcrCompletedEvent",
    "ParseCompletedEvent",
    "CodingCompletedEvent",
    "PredictCompletedEvent",
    "ValidationCompletedEvent",
    "SubmissionCompletedEvent",
]
