from __future__ import annotations

import logging
import os as _os

# ── audit helper ──
import sys as _sys
import uuid
from pathlib import Path, PurePosixPath

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import Claim, Document
from .schemas import ClaimListOut, ClaimOut

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
try:
    from libs.utils.audit import AuditLogger
except Exception:
    AuditLogger = None  # type: ignore

def _audit(db, action: str, claim_id=None, metadata=None):
    try:
        if AuditLogger:
            AuditLogger(db, "ingress").log(action, claim_id=claim_id, metadata=metadata)
    except Exception:
        logger.debug("Audit log failed for %s", action, exc_info=True)

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("ingress")

RAW_STORAGE = Path(settings.storage_root).resolve()
RAW_STORAGE.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ClaimGPT Ingress Service")

# ------------------------------------------------------------------ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ observability
try:
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from libs.observability.metrics import PrometheusMiddleware, init_metrics, metrics_endpoint
    from libs.observability.tracing import init_tracing, instrument_fastapi
    init_tracing("ingress")
    init_metrics("ingress")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


# ------------------------------------------------------------------ lifecycle
@app.on_event("shutdown")
def _shutdown():
    engine.dispose()
    logger.info("DB engine disposed")


# ------------------------------------------------------------------ deps
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")


def _safe_filename(raw: str | None) -> str:
    """Strip directory components to prevent path-traversal via filename."""
    if not raw:
        return "upload.bin"
    return PurePosixPath(raw).name or "upload.bin"


def _trigger_workflow(claim_id: str) -> None:
    """Fire-and-forget workflow trigger after upload."""
    import httpx
    try:
        resp = httpx.post(
            f"{settings.workflow_url}/start/{claim_id}",
            timeout=10.0,
        )
        logger.info("Workflow triggered for %s — %d", claim_id, resp.status_code)
    except Exception:
        logger.warning("Failed to trigger workflow for %s", claim_id, exc_info=True)


# ------------------------------------------------------------------ routes
router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.post("/claims", response_model=ClaimOut, status_code=201)
async def create_claim(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    policy_id: str = Form(None),
    patient_id: str = Form(None),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # --- validate all files first
    file_data: list[tuple[UploadFile, bytes, str]] = []
    for file in files:
        if file.content_type not in settings.allowed_content_types:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{file.content_type}' for '{file.filename}'. "
                f"Allowed: {', '.join(sorted(settings.allowed_content_types))}",
            )
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File '{file.filename}' too large ({len(content)} bytes). Max: {settings.max_upload_bytes} bytes",
            )
        safe_name = _safe_filename(file.filename)
        file_data.append((file, content, safe_name))

    # --- persist claim row
    claim = Claim(
        policy_id=policy_id,
        patient_id=patient_id,
        status="UPLOADED",
        source="PATIENT",
    )
    db.add(claim)
    db.flush()  # get claim.id without committing yet

    # --- save all files and create document rows
    saved_paths: list[Path] = []
    for idx, (file, content, safe_name) in enumerate(file_data):
        ext = Path(safe_name).suffix or ".bin"
        stored_name = f"{claim.id}_{idx}{ext}" if len(file_data) > 1 else f"{claim.id}{ext}"
        local_path = RAW_STORAGE / stored_name

        try:
            async with aiofiles.open(local_path, "wb") as f:
                await f.write(content)
            saved_paths.append(local_path)
        except OSError:
            # Clean up already-saved files
            for p in saved_paths:
                p.unlink(missing_ok=True)
            db.rollback()
            logger.exception("Failed to write uploaded file to disk")
            raise HTTPException(status_code=500, detail="Failed to store uploaded file")

        doc = Document(
            claim_id=claim.id,
            file_name=safe_name,
            file_type=file.content_type,
            minio_path=str(local_path),
        )
        db.add(doc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        for p in saved_paths:
            p.unlink(missing_ok=True)
        logger.exception("DB commit failed during claim creation")
        raise HTTPException(status_code=500, detail="Failed to save claim")

    logger.info("Claim %s created (%d files)", claim.id, len(file_data))
    db.refresh(claim)

    _audit(db, "CLAIM_CREATED", claim_id=claim.id, metadata={
        "files": [s for _, _, s in file_data],
        "file_count": len(file_data),
        "policy_id": policy_id,
        "patient_id": patient_id,
    })

    # Auto-trigger workflow pipeline
    background_tasks.add_task(_trigger_workflow, str(claim.id))

    return ClaimOut.model_validate(claim).model_dump(mode="json")


@router.get("/claims", response_model=ClaimListOut)
def list_claims(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total = db.query(Claim).count()
    claims = (
        db.query(Claim)
        .order_by(Claim.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ClaimListOut(claims=claims, total=total)


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("/claims/{claim_id}/file")
def download_original_file(claim_id: str, db: Session = Depends(get_db)):
    cid = _parse_uuid(claim_id)

    doc = (
        db.query(Document)
        .filter(Document.claim_id == cid)
        .order_by(Document.uploaded_at.desc())
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="No document found for claim")

    file_path = Path(doc.minio_path).resolve()

    # prevent path traversal — file must be under RAW_STORAGE
    if not str(file_path).startswith(str(RAW_STORAGE)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found on disk")

    return FileResponse(str(file_path), filename=doc.file_name)


@router.post("/claims/{claim_id}/documents", response_model=ClaimOut, status_code=201)
async def add_documents_to_claim(
    claim_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Add supporting documents to an existing claim."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # --- validate all files
    file_data: list[tuple[UploadFile, bytes, str]] = []
    for file in files:
        if file.content_type not in settings.allowed_content_types:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{file.content_type}' for '{file.filename}'. "
                f"Allowed: {', '.join(sorted(settings.allowed_content_types))}",
            )
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File '{file.filename}' too large ({len(content)} bytes). Max: {settings.max_upload_bytes} bytes",
            )
        safe_name = _safe_filename(file.filename)
        file_data.append((file, content, safe_name))

    # --- count existing docs for naming
    existing_count = db.query(Document).filter(Document.claim_id == cid).count()

    # --- save files and create document rows
    saved_paths: list[Path] = []
    for idx, (file, content, safe_name) in enumerate(file_data):
        ext = Path(safe_name).suffix or ".bin"
        stored_name = f"{claim.id}_{existing_count + idx}{ext}"
        local_path = RAW_STORAGE / stored_name

        try:
            async with aiofiles.open(local_path, "wb") as f:
                await f.write(content)
            saved_paths.append(local_path)
        except OSError:
            for p in saved_paths:
                p.unlink(missing_ok=True)
            db.rollback()
            logger.exception("Failed to write uploaded file to disk")
            raise HTTPException(status_code=500, detail="Failed to store uploaded file")

        doc = Document(
            claim_id=claim.id,
            file_name=safe_name,
            file_type=file.content_type,
            minio_path=str(local_path),
        )
        db.add(doc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        for p in saved_paths:
            p.unlink(missing_ok=True)
        logger.exception("DB commit failed adding documents")
        raise HTTPException(status_code=500, detail="Failed to save documents")

    logger.info("Added %d docs to claim %s", len(file_data), claim.id)
    db.refresh(claim)

    _audit(db, "DOCUMENTS_ADDED", claim_id=claim.id, metadata={
        "files": [s for _, _, s in file_data],
        "file_count": len(file_data),
        "total_documents": existing_count + len(file_data),
    })

    # Re-trigger workflow to reprocess with new documents
    background_tasks.add_task(_trigger_workflow, str(claim.id))

    return ClaimOut.model_validate(claim).model_dump(mode="json")


@router.delete("/claims/{claim_id}/documents/{doc_id}", response_model=ClaimOut)
def delete_document(
    claim_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
):
    """Delete a single document from a claim."""
    cid = _parse_uuid(claim_id)
    did = _parse_uuid(doc_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    doc = db.query(Document).filter(Document.id == did, Document.claim_id == cid).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Prevent deleting the last document
    doc_count = db.query(Document).filter(Document.claim_id == cid).count()
    if doc_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only document. Delete the claim instead.")

    # Remove file from disk
    try:
        p = Path(doc.minio_path).resolve()
        if str(p).startswith(str(RAW_STORAGE)):
            p.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to delete file %s", doc.minio_path)

    db.delete(doc)
    db.commit()
    db.refresh(claim)
    _audit(db, "DOCUMENT_DELETED", claim_id=cid, metadata={"document_id": str(did), "file_name": doc.file_name})
    logger.info("Deleted doc %s from claim %s", doc_id, claim_id)
    return ClaimOut.model_validate(claim).model_dump(mode="json")


@router.delete("/claims/{claim_id}", status_code=204)
def delete_claim(claim_id: str, db: Session = Depends(get_db)):
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # delete stored files from disk
    docs = db.query(Document).filter(Document.claim_id == cid).all()
    for doc in docs:
        try:
            p = Path(doc.minio_path).resolve()
            if str(p).startswith(str(RAW_STORAGE)):
                p.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete file %s", doc.minio_path)

    doc_names = [d.file_name for d in docs]
    db.delete(claim)
    db.commit()
    _audit(db, "CLAIM_DELETED", claim_id=cid, metadata={"documents": doc_names})
    logger.info("Claim %s deleted", claim_id)


# ── Include router (standalone mode) ──
app.include_router(router)
