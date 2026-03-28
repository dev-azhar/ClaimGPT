import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
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

    documents = relationship("Document", back_populates="claim", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)

    file_name = Column(Text, nullable=False)
    file_type = Column(Text, nullable=True)
    minio_path = Column(Text, nullable=False)   # keep name as per schema even if local path now
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="documents")