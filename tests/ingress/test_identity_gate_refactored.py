import pytest
import uuid
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from libs.shared.models import Base, DocValidation, ParsedField
from services.ingress.app.main import Document

# Compile JSONB to JSON for SQLite compatibility in tests
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_apply_identity_gate_with_scanned_pdf_or_image(db_session):
    claim_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    
    # Create a dummy Document
    doc = Document(
        id=doc_id,
        claim_id=claim_id,
        file_name="invoice.png",
        file_type="image/png",
        minio_path="s3://bucket/invoice.png",
        content_hash="mock-hash-1"
    )
    
    # Mock _extract_text_for_identity to return empty string (as an image has no text synchronously)
    with patch("services.ingress.app.main._extract_text_for_identity", return_value=""), \
         patch("services.ingress.app.main._existing_identity_anchor", return_value=(None, None)):
        
        from services.ingress.app.main import _apply_identity_gate
        
        result = _apply_identity_gate(db_session, claim_id, [doc])
        
        # Verify document was accepted for OCR
        assert result["accepted_count"] == 1
        assert "invoice.png" in result["accepted_docs"]
        
        # Verify DocValidation entry was recorded as PENDING/VALID (not excluded)
        val = db_session.query(DocValidation).filter(
            DocValidation.claim_id == claim_id,
            DocValidation.document_id == doc_id
        ).first()
        
        assert val is not None
        assert val.status == "VALID"
        assert val.patient_match == "PENDING"
        assert val.validation_metadata["excluded_from_pipeline"] is False


def test_existing_identity_anchor_fallback_to_parsed_fields(db_session):
    claim_id = uuid.uuid4()
    
    # Insert a ParsedField representing the patient name from the first batch
    db_session.add(ParsedField(
        claim_id=claim_id,
        field_name="patient_name",
        field_value="John Doe"
    ))
    db_session.add(ParsedField(
        claim_id=claim_id,
        field_name="dob",
        field_value="1990-01-01"
    ))
    db_session.commit()
    
    from services.ingress.app.main import _existing_identity_anchor
    
    # Retrieve anchor and assert it falls back to the ParsedField
    anchor_name, anchor_dob = _existing_identity_anchor(db_session, claim_id)
    assert anchor_name == "John Doe"
    assert anchor_dob == "1990-01-01"


def test_existing_identity_anchor_fallback_to_other_validations(db_session):
    claim_id = uuid.uuid4()
    
    # Insert another valid DocValidation entry (not IDENTITY_GATE)
    db_session.add(DocValidation(
        claim_id=claim_id,
        document_id=uuid.uuid4(),
        status="VALID",
        doc_type="LAB_REPORT",
        doc_type_label="Laboratory Report",
        patient_name="Jane Smith",
        validation_metadata={"identity_dob": "1995-05-05"}
    ))
    db_session.commit()
    
    from services.ingress.app.main import _existing_identity_anchor
    
    # Retrieve anchor and assert it falls back to the other validation record
    anchor_name, anchor_dob = _existing_identity_anchor(db_session, claim_id)
    assert anchor_name == "Jane Smith"
    assert anchor_dob == "1995-05-05"
