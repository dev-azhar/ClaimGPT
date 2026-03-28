from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID


class ChatMessageOut(BaseModel):
    id: UUID
    role: Optional[str] = None
    message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FieldAction(BaseModel):
    """A single add/modify/delete action on a claim's parsed field."""
    action: str  # "add" | "modify" | "delete"
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    claim_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    role: str
    message: str
    claim_id: Optional[str] = None
    suggestions: List[str] = []
    field_actions: List[FieldAction] = []


class FieldActionRequest(BaseModel):
    claim_id: str
    actions: List[FieldAction]


class ChatHistoryOut(BaseModel):
    session_id: str
    messages: List[ChatMessageOut] = []
