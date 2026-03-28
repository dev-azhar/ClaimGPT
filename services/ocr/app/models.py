import uuid
from sqlalchemy import Column, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

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

    documents = relationship("Document", back_populates="claim")
    ocr_jobs = relationship("OcrJob", back_populates="claim")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(Text, nullable=False)
    file_type = Column(Text, nullable=True)
    minio_path = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="documents")
    ocr_results = relationship("OcrResult", back_populates="document", cascade="all, delete-orphan")


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="ocr_results")


class OcrJob(Base):
    __tablename__ = "ocr_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False, default="QUEUED")  # QUEUED | PROCESSING | COMPLETED | FAILED
    total_documents = Column(Integer, nullable=False, default=0)
    processed_documents = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    claim = relationship("Claim", back_populates="ocr_jobs")


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
    scan_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
