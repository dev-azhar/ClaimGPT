import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from libs.shared.models import Base, Claim, Document
from services.ingress.app.main import app, get_db

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()

def test_add_documents_sets_status_to_uploaded(db_session):
    claim_id = uuid.uuid4()
    claim = Claim(id=claim_id, status="COMPLETED", source="PATIENT")
    db_session.add(claim)
    
    # Add an existing document
    existing_doc = Document(
        id=uuid.uuid4(),
        claim_id=claim_id,
        file_name="existing.pdf",
        file_type="application/pdf",
        minio_path="s3://bucket/existing.pdf",
        content_hash="hash-existing"
    )
    db_session.add(existing_doc)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session

    client = TestClient(app)

    # Mock file upload
    file_content = b"fake file content"
    files = [("files", ("new_doc.pdf", file_content, "application/pdf"))]

    class AsyncContextManagerMock:
        async def __aenter__(self):
            mock_file = MagicMock()
            mock_file.write = AsyncMock()
            return mock_file
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("services.ingress.app.main._resolve_content_type", return_value=("application/pdf", True)), \
         patch("services.ingress.app.main._extract_text_for_identity", return_value=""), \
         patch("services.ingress.app.main._enqueue_pipeline", return_value="mock-task-id") as mock_enqueue, \
         patch("services.ingress.app.main.RAW_STORAGE", new=MagicMock()), \
         patch("aiofiles.open") as mock_aioopen:
         
        mock_aioopen.return_value = AsyncContextManagerMock()

        response = client.post(f"/claims/{claim_id}/documents", files=files)
        
        assert response.status_code == 201
        
        # Verify claim status was updated to UPLOADED in the DB
        db_session.refresh(claim)
        assert claim.status == "UPLOADED"
        mock_enqueue.assert_called_once_with(str(claim_id))

    del app.dependency_overrides[get_db]


def test_add_duplicate_documents_sets_status_to_uploaded(db_session):
    claim_id = uuid.uuid4()
    claim = Claim(id=claim_id, status="COMPLETED", source="PATIENT")
    db_session.add(claim)
    
    # Add an existing document
    existing_doc = Document(
        id=uuid.uuid4(),
        claim_id=claim_id,
        file_name="existing.pdf",
        file_type="application/pdf",
        minio_path="s3://bucket/existing.pdf",
        content_hash="hash-existing"
    )
    db_session.add(existing_doc)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session

    client = TestClient(app)

    # Mock file upload of duplicate document
    files = [("files", ("existing.pdf", b"fake file content", "application/pdf"))]

    with patch("services.ingress.app.main._resolve_content_type", return_value=("application/pdf", True)), \
         patch("services.ingress.app.main.hashlib.sha256") as mock_sha, \
         patch("services.ingress.app.main._enqueue_pipeline", return_value="mock-task-id") as mock_enqueue:
         
        mock_hash_obj = MagicMock()
        mock_hash_obj.hexdigest.return_value = "hash-existing"
        mock_sha.return_value = mock_hash_obj

        response = client.post(f"/claims/{claim_id}/documents", files=files)
        
        assert response.status_code == 200
        
        # Verify claim status was updated to UPLOADED in the DB
        db_session.refresh(claim)
        assert claim.status == "UPLOADED"
        mock_enqueue.assert_called_once_with(str(claim_id))

    del app.dependency_overrides[get_db]
