import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from libs.shared.db import Base

# --- Independent Lookup / Reference Tables ---

class TpaProvider(Base):
    __tablename__ = "tpa_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(Text, unique=True, nullable=False)
    name = Column(Text, nullable=False)
    logo = Column(Text, default="🏥")
    provider_type = Column(Text, default="Private")
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- The Core Claim Model ---

class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(Text, nullable=True)
    patient_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="UPLOADED")
    source = Column(Text, nullable=True, default="PATIENT")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships (Targeted for High-Scale Cleanup)
    documents = relationship("Document", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    submissions = relationship("Submission", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    audit_logs = relationship("AuditLog", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    ocr_jobs = relationship("OcrJob", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    parse_jobs = relationship("ParseJob", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    parsed_fields = relationship("ParsedField", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    medical_entities = relationship("MedicalEntity", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    features = relationship("Feature", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    predictions = relationship("Prediction", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    validations = relationship("Validation", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    workflow_state = relationship("WorkflowState", back_populates="claim", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    workflow_jobs = relationship("WorkflowJob", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    scan_analyses = relationship("ScanAnalysis", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    doc_validations = relationship("DocValidation", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)
    chat_messages = relationship("ChatMessage", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True)


# --- Supporting Models (Top Level) ---

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    payer = Column(Text, nullable=True)
    request_payload = Column(JSONB, nullable=True)
    response_payload = Column(JSONB, nullable=True)
    status = Column(Text, nullable=False, default="PENDING")
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="submissions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    
    # RENAME: 'metadata' is reserved in SQLAlchemy Declarative
    audit_metadata = Column("metadata", JSONB, nullable=True)
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    claim = relationship("Claim", back_populates="audit_logs")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(Text, nullable=False)
    file_type = Column(Text, nullable=True)
    minio_path = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(Text, index=True, nullable=False)  # SHA-256 fingerprint of file content

    claim = relationship("Claim", back_populates="documents")
    ocr_results = relationship("OcrResult", back_populates="document", cascade="all, delete-orphan", passive_deletes=True)
    scan_analyses = relationship("ScanAnalysis", back_populates="document")


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="ocr_results")


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

    claim = relationship("Claim", back_populates="parsed_fields")


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

    claim = relationship("Claim", back_populates="medical_entities")
    codes = relationship("MedicalCode", back_populates="entity", cascade="all, delete-orphan")


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
    estimated_cost = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    entity = relationship("MedicalEntity", back_populates="codes")


class Feature(Base):
    __tablename__ = "features"

    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    feature_vector = Column(JSONB, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="features")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    rejection_score = Column(Float, nullable=True)
    top_reasons = Column(JSONB, nullable=True)
    model_name = Column(Text, nullable=True)
    model_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="predictions")


class Validation(Base):
    __tablename__ = "validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Text, nullable=True)
    rule_name = Column(Text, nullable=True)
    severity = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    passed = Column(Boolean, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="validations")


class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(Text, nullable=True)
    status = Column(Text, nullable=True)
    retries = Column(Integer, default=0)
    current_step = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    claim = relationship("Claim", back_populates="workflow_jobs")


class WorkflowState(Base):
    __tablename__ = "workflow_state"

    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    current_step = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    claim = relationship("Claim", back_populates="workflow_state")


class ScanAnalysis(Base):
    __tablename__ = "scan_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    scan_type = Column(Text, nullable=False)
    body_part = Column(Text, nullable=True)
    modality = Column(Text, nullable=True)
    findings = Column(JSONB, nullable=True)
    impression = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    
    # RENAME: 'metadata' is reserved
    scan_metadata = Column("metadata", JSONB, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="scan_analyses")
    document = relationship("Document", back_populates="scan_analyses")


class DocValidation(Base):
    __tablename__ = "document_validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False)
    doc_type = Column(Text, nullable=True)
    doc_type_label = Column(Text, nullable=True)
    is_medical = Column(Integer, nullable=False, default=1)
    patient_match = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    patient_name = Column(Text, nullable=True)
    patient_id_extracted = Column(Text, nullable=True)
    issues = Column(JSONB, nullable=True)
    
    # RENAME: 'metadata' is reserved
    validation_metadata = Column("metadata", JSONB, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="doc_validations")


class OcrJob(Base):
    __tablename__ = "ocr_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False, default="QUEUED")
    total_documents = Column(Integer, nullable=False, default=0)
    processed_documents = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    claim = relationship("Claim", back_populates="ocr_jobs")


class ParseJob(Base):
    __tablename__ = "parse_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False, default="QUEUED")
    total_documents = Column(Integer, nullable=False, default=0)
    processed_documents = Column(Integer, nullable=False, default=0)
    set_hash = Column(Text, index=True, nullable=True)  # Set-based idempotency hash
    model_version = Column(Text, nullable=True)
    used_fallback = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    claim = relationship("Claim", back_populates="parse_jobs")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="chat_messages")