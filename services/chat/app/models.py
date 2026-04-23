import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from .db import Base


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(Text, nullable=True)
    patient_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="UPLOADED")
    source = Column(Text, nullable=True, default="PATIENT")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(Text, nullable=False)
    file_type = Column(Text, nullable=True)
    minio_path = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ParsedField(Base):
    __tablename__ = "parsed_fields"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(Text, nullable=False)
    field_value = Column(Text, nullable=True)
    bounding_box = Column(JSONB, nullable=True)
    source_page = Column(Integer, nullable=True)
    model_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    rejection_score = Column(Float, nullable=True)
    top_reasons = Column(JSONB, nullable=True)
    model_name = Column(Text, nullable=True)
    model_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Validation(Base):
    __tablename__ = "validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    rule_id = Column(Text, nullable=True)
    rule_name = Column(Text, nullable=True)
    severity = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    passed = Column(Text, nullable=True)  # stored as boolean in DB but safe as text
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now())


class MedicalCode(Base):
    __tablename__ = "medical_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    code = Column(Text, nullable=False)
    code_system = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    is_primary = Column(Text, nullable=True)  # boolean
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MedicalEntity(Base):
    __tablename__ = "medical_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    entity_text = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)  # DIAGNOSIS / PROCEDURE / MEDICATION
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    role = Column(Text, nullable=True)     # USER / SYSTEM / ASSISTANT
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
