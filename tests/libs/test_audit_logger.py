import pytest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from libs.shared.models import Base, AuditLog
from libs.utils.audit import AuditLogger

# Teach SQLAlchemy SQLite compiler how to render PostgreSQL's JSONB type as JSON
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

def test_audit_logger_success():
    # Setup in-memory SQLite database
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        logger = AuditLogger(session, "test_service")
        claim_uuid = uuid.uuid4()
        
        # Log an event
        logger.log(
            action="TEST_ACTION",
            claim_id=claim_uuid,
            metadata={"key": "value"}
        )
        
        # Query and assert the database row was successfully created
        log_entry = session.query(AuditLog).first()
        assert log_entry is not None
        assert log_entry.action == "TEST_ACTION"
        assert log_entry.claim_id == claim_uuid
        assert log_entry.actor == "test_service"
        assert log_entry.audit_metadata == {"key": "value"}
        assert log_entry.created_at is not None
    finally:
        session.close()
