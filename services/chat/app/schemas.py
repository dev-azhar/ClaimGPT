from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


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




class OCRPage(BaseModel):
    page: int
    text: str
    confidence: Optional[float]


class PredictionModel(BaseModel):
    rejection_score: Optional[float]
    top_reasons: Optional[List[str]]
    model_name: Optional[str]


class ValidationModel(BaseModel):
    rule_id: Optional[str]
    rule_name: Optional[str]
    severity: Optional[str]
    message: Optional[str]
    passed: bool


class MedicalCodeModel(BaseModel):
    code: str
    code_type: Optional[str]
    description: Optional[str]
    confidence: Optional[float]


class MedicalEntityModel(BaseModel):
    text: str
    type: Optional[str]
    confidence: Optional[float]


class ClaimContext(BaseModel):
    claim_id: str
    status: Optional[str]
    policy_id: Optional[str]

    parsed_fields: Dict[str, Any]
    parsed_fields_by_document_type: Optional[Dict[str, Any]]

    full_ocr_text: Optional[str]
    relevant_text: Optional[str]
    ocr_page_count: int
    ocr_by_document_type: Optional[Dict[str, Any]]

    predictions: List[PredictionModel]
    validations: List[ValidationModel]
    medical_codes: List[MedicalCodeModel]
    medical_entities: List[MedicalEntityModel]
