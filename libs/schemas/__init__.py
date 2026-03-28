"""Shared Pydantic schemas for inter-service communication."""

from .claim import ClaimEvent, ClaimStatus
from .events import (
    EventEnvelope,
    ClaimIngestedEvent,
    OcrCompletedEvent,
    ParseCompletedEvent,
    CodingCompletedEvent,
    PredictCompletedEvent,
    ValidationCompletedEvent,
    SubmissionCompletedEvent,
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
