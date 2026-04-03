from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatMessageOut(BaseModel):
    id: UUID
    role: str | None = None
    message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FieldAction(BaseModel):
    """A single add/modify/delete action on a claim's parsed field."""
    action: str  # "add" | "modify" | "delete"
    field_name: str
    old_value: str | None = None
    new_value: str | None = None


class ChatRequest(BaseModel):
    message: str
    claim_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    role: str
    message: str
    claim_id: str | None = None
    suggestions: list[str] = []
    field_actions: list[FieldAction] = []


class FieldActionRequest(BaseModel):
    claim_id: str
    actions: list[FieldAction]


class ChatHistoryOut(BaseModel):
    session_id: str
    messages: list[ChatMessageOut] = []
