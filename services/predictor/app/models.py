import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Text
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


class MedicalEntity(Base):
    __tablename__ = "medical_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    entity_text = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MedicalCode(Base):
    __tablename__ = "medical_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("medical_entities.id"), nullable=True)
    code = Column(Text, nullable=False)
    code_system = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Feature(Base):
    __tablename__ = "features"

    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    feature_vector = Column(JSONB, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    rejection_score = Column(Float, nullable=True)
    top_reasons = Column(JSONB, nullable=True)
    model_name = Column(Text, nullable=True)
    model_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
