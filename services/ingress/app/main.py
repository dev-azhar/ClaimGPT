from __future__ import annotations

import hashlib
import logging
import os
import re

# ── audit helper ──
import sys as _sys
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import aiofiles
from celery import chain
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.shared_tasks import coding_task, ocr_task, parser_task, risk_task, validator_task

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import Claim, Document, DocValidation
from .schemas import ClaimListOut, ClaimOut

_sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
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


def _compute_upload_sha256(file_data: list[tuple[UploadFile, bytes, str]]) -> str:
    hasher = hashlib.sha256()
    for _, content, safe_name in file_data:
        hasher.update(safe_name.encode("utf-8", errors="ignore"))
        hasher.update(b"\x00")
        hasher.update(content)
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _find_completed_claim_by_upload_hash(db: Session, upload_sha256: str) -> Claim | None:
    row = db.execute(
        text(
            """
            SELECT c.id
            FROM claims c
            JOIN audit_logs a ON a.claim_id = c.id
            WHERE a.action = 'CLAIM_CREATED'
              AND a.metadata->>'upload_sha256' = :upload_sha256
              AND c.status = 'COMPLETED'
            ORDER BY c.created_at DESC
            LIMIT 1
            """
        ),
        {"upload_sha256": upload_sha256},
    ).first()
    if not row:
        return None
    return db.query(Claim).filter(Claim.id == row[0]).first()


def _enqueue_pipeline(claim_id: str) -> str:
    workflow_chain = (
        ocr_task.s(claim_id)
        | parser_task.s()
        | coding_task.s()
        | risk_task.s()
        | validator_task.s()
    )
    result = workflow_chain.apply_async()
    return str(result.id)


_PATIENT_NAME_PATTERNS = [
    re.compile(r"(?im)(?:^|\n)\s*(?:patient\s*name|name\s*of\s*patient)\s*[:\-]\s*([^\n\r|]+)"),
]

_DOB_PATTERNS = [
    re.compile(r"(?im)(?:^|\n)\s*(?:date\s*of\s*birth|dob|d\.o\.b)\s*[:\-]\s*([^\n\r|]+)"),
]

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _canonical_name(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _normalize_dob(value: str | None) -> str:
    if not value:
        return ""
    raw = re.sub(r"\s+", " ", value).strip().replace(",", "")
    m_num = re.fullmatch(r"(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{2,4})", raw)
    if m_num:
        day, month, year = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if year < 100:
            year += 2000 if year < 50 else 1900
        return f"{year:04d}-{month:02d}-{day:02d}"

    m_mon = re.fullmatch(r"(\d{1,2})[\-/. ]([A-Za-z]{3,9})[\-/. ](\d{2,4})", raw)
    if m_mon:
        day, month_token, year = int(m_mon.group(1)), m_mon.group(2).lower(), int(m_mon.group(3))
        month = _MONTHS.get(month_token)
        if month:
            if year < 100:
                year += 2000 if year < 50 else 1900
            return f"{year:04d}-{month:02d}-{day:02d}"

    m_alt = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{2,4})", raw)
    if m_alt:
        month_token, day, year = m_alt.group(1).lower(), int(m_alt.group(2)), int(m_alt.group(3))
        month = _MONTHS.get(month_token)
        if month:
            if year < 100:
                year += 2000 if year < 50 else 1900
            return f"{year:04d}-{month:02d}-{day:02d}"

    return raw.lower()


def _extract_text_for_identity(file_path: Path, file_type: str | None) -> str:
    file_type = (file_type or "").lower()
    suffix = file_path.suffix.lower()

    if file_type == "application/pdf" or suffix == ".pdf":
        try:
            import pdfplumber

            parts: list[str] = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages[:5]:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t)
            return "\n".join(parts)
        except Exception:
            return ""

    if suffix == ".docx":
        try:
            import docx

            d = docx.Document(str(file_path))
            return "\n".join(p.text for p in d.paragraphs if p.text)
        except Exception:
            return ""

    if suffix in {".xlsx", ".xlsm"}:
        try:
            import openpyxl

            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
            lines: list[str] = []
            for ws in wb.worksheets[:3]:
                for row in ws.iter_rows(min_row=1, max_row=60, values_only=True):
                    vals = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if vals:
                        lines.append(" | ".join(vals))
            return "\n".join(lines)
        except Exception:
            return ""

    if suffix in {".txt", ".csv", ".json", ".xml", ".html", ".htm"}:
        try:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    return ""


def _extract_identity_from_text(text: str) -> tuple[str | None, str | None]:
    if not text:
        return None, None

    patient_name: str | None = None
    dob: str | None = None

    for pat in _PATIENT_NAME_PATTERNS:
        m = pat.search(text)
        if m:
            patient_name = m.group(1).strip()
            break

    for pat in _DOB_PATTERNS:
        m = pat.search(text)
        if m:
            dob = m.group(1).strip()
            break

    if patient_name:
        patient_name = re.sub(r"\s+", " ", patient_name).strip()
    if dob:
        dob = re.sub(r"\s+", " ", dob).strip()
    return patient_name, dob


def _existing_identity_anchor(db: Session, claim_id: uuid.UUID) -> tuple[str | None, str | None]:
    rows = (
        db.query(DocValidation)
        .filter(
            DocValidation.claim_id == claim_id,
            DocValidation.doc_type == "IDENTITY_GATE",
            DocValidation.status == "VALID",
        )
        .order_by(DocValidation.created_at.asc())
        .all()
    )
    if not rows:
        return None, None

    locked = []
    for row in rows:
        md = row.validation_metadata or {}
        if md.get("anchor_locked"):
            locked.append(row)
    picked = locked[0] if locked else rows[0]
    md = picked.validation_metadata or {}
    return picked.patient_name, md.get("identity_dob")


def _upsert_identity_validation(
    db: Session,
    *,
    claim_id: uuid.UUID,
    document_id: uuid.UUID,
    file_name: str,
    status: str,
    patient_match: str,
    patient_name: str | None,
    dob: str | None,
    excluded: bool,
    needs_manual_review: bool,
    reason: str,
    anchor_locked: bool,
) -> None:
    db.query(DocValidation).filter(
        DocValidation.claim_id == claim_id,
        DocValidation.document_id == document_id,
        DocValidation.doc_type == "IDENTITY_GATE",
    ).delete(synchronize_session=False)

    metadata: dict[str, Any] = {
        "phase": "UPLOAD_IDENTITY_GATE",
        "file_name": file_name,
        "identity_dob": dob,
        "excluded_from_pipeline": excluded,
        "needs_manual_review": needs_manual_review,
        "reason": reason,
        "anchor_locked": anchor_locked,
        "checked_at_utc": datetime.utcnow().isoformat() + "Z",
    }

    db.add(DocValidation(
        claim_id=claim_id,
        document_id=document_id,
        status=status,
        doc_type="IDENTITY_GATE",
        doc_type_label="Identity Gate",
        is_medical=1,
        patient_match=patient_match,
        confidence=1.0,
        patient_name=patient_name,
        patient_id_extracted=None,
        issues=[reason],
        validation_metadata=metadata,
    ))


def _apply_identity_gate(
    db: Session,
    claim_id: uuid.UUID,
    documents: list[Document],
) -> dict[str, Any]:
    anchor_name, anchor_dob = _existing_identity_anchor(db, claim_id)
    anchor_name_key = _canonical_name(anchor_name)

    accepted_docs: list[str] = []
    rejected_docs: list[dict[str, str]] = []
    manual_review_required = False

    for doc in documents:
        text = _extract_text_for_identity(Path(doc.minio_path), doc.file_type)
        patient_name, dob_raw = _extract_identity_from_text(text)
        dob = _normalize_dob(dob_raw) if dob_raw else ""

        if not patient_name:
            manual_review_required = True
            reason = "Document missing required patient_name"
            _upsert_identity_validation(
                db,
                claim_id=claim_id,
                document_id=doc.id,
                file_name=doc.file_name,
                status="INVALID",
                patient_match="NO_DATA",
                patient_name=patient_name,
                dob=dob_raw,
                excluded=True,
                needs_manual_review=True,
                reason=reason,
                anchor_locked=False,
            )
            rejected_docs.append({"file_name": doc.file_name, "reason": reason})
            continue

        name_key = _canonical_name(patient_name)

        if not anchor_name_key:
            anchor_name = patient_name
            anchor_dob = dob
            anchor_name_key = name_key
            _upsert_identity_validation(
                db,
                claim_id=claim_id,
                document_id=doc.id,
                file_name=doc.file_name,
                status="VALID",
                patient_match="MATCH",
                patient_name=patient_name,
                dob=dob,
                excluded=False,
                needs_manual_review=False,
                reason="Anchor identity established (name-only)",
                anchor_locked=True,
            )
            accepted_docs.append(doc.file_name)
            continue

        if name_key == anchor_name_key:
            _upsert_identity_validation(
                db,
                claim_id=claim_id,
                document_id=doc.id,
                file_name=doc.file_name,
                status="VALID",
                patient_match="MATCH",
                patient_name=patient_name,
                dob=dob,
                excluded=False,
                needs_manual_review=False,
                reason="Identity matched claim anchor (name-only)",
                anchor_locked=False,
            )
            accepted_docs.append(doc.file_name)
            continue

        manual_review_required = True
        reason = "Patient name mismatch with first-batch claim anchor"
        _upsert_identity_validation(
            db,
            claim_id=claim_id,
            document_id=doc.id,
            file_name=doc.file_name,
            status="INVALID",
            patient_match="MISMATCH",
            patient_name=patient_name,
            dob=dob,
            excluded=True,
            needs_manual_review=True,
            reason=reason,
            anchor_locked=False,
        )
        rejected_docs.append({"file_name": doc.file_name, "reason": reason})

    return {
        "accepted_count": len(accepted_docs),
        "accepted_docs": accepted_docs,
        "rejected_docs": rejected_docs,
        "manual_review_required": manual_review_required,
        "anchor_name": anchor_name,
        "anchor_dob": anchor_dob,
    }


# ------------------------------------------------------------------ routes
router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.post("/claims", response_model=ClaimOut, status_code=201)
async def create_claim(
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

    upload_sha256 = _compute_upload_sha256(file_data)
    existing_claim = _find_completed_claim_by_upload_hash(db, upload_sha256)
    if existing_claim:
        logger.info("Idempotent upload hit: returning completed claim %s", existing_claim.id)
        db.refresh(existing_claim)
        payload = ClaimOut.model_validate(existing_claim).model_dump(mode="json")
        payload["task_id"] = None
        payload["already_exists"] = True
        payload["existing_claim_id"] = str(existing_claim.id)
        # Add a preview/report URL if your UI supports it (adjust path as needed)
        payload["report_url"] = f"/submission/claims/{existing_claim.id}/preview"
        return JSONResponse(status_code=200, content=payload)

    # --- persist claim row
    claim = Claim(
        policy_id=policy_id,
        patient_id=patient_id,
        status="UPLOADED",
        source="PATIENT",
    )
    db.add(claim)
    db.flush()  # get claim.id without committing yet
    logger.info("Upload received -> claim=%s files=%d policy_id=%s patient_id=%s", claim.id, len(file_data), policy_id, patient_id)

    # --- save all files and create document rows
    saved_paths: list[Path] = []
    new_docs: list[Document] = []
    for idx, (file, content, safe_name) in enumerate(file_data):
        ext = Path(safe_name).suffix or ".bin"
        stored_name = f"{claim.id}_{idx}{ext}" if len(file_data) > 1 else f"{claim.id}{ext}"
        local_path = RAW_STORAGE / stored_name

        logger.info(f"[INGRESS DEBUG] Attempting to write file: {local_path}")
        try:
            async with aiofiles.open(local_path, "wb") as f:
                await f.write(content)
            # Force flush and fsync to ensure file is visible to other containers
            with open(local_path, "rb+") as sync_f:
                sync_f.flush()
                os.fsync(sync_f.fileno())
            saved_paths.append(local_path)
            logger.info(f"[INGRESS DEBUG] Successfully wrote file: {local_path}")
            logger.info(f"[INGRESS DEBUG] Directory listing after write: {os.listdir(RAW_STORAGE)}")
        except OSError as e:
            # Clean up already-saved files
            for p in saved_paths:
                p.unlink(missing_ok=True)
            db.rollback()
            logger.exception(f"[INGRESS DEBUG] Failed to write uploaded file to disk: {local_path} | Exception: {e}")
            logger.info(f"[INGRESS DEBUG] Directory listing on error: {os.listdir(RAW_STORAGE)}")
            raise HTTPException(status_code=500, detail="Failed to store uploaded file")

        doc = Document(
            claim_id=claim.id,
            file_name=safe_name,
            file_type=file.content_type,
            minio_path=str(local_path),
        )
        db.add(doc)
        new_docs.append(doc)
        logger.info("Saved upload file -> claim=%s file=%s type=%s path=%s", claim.id, safe_name, file.content_type, local_path)

    db.flush()
    gate_result = _apply_identity_gate(db, claim.id, new_docs)
    if gate_result["accepted_count"] == 0:
        claim.status = "MANUAL_REVIEW_REQUIRED"

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

    # Extra sync and directory listing for robust audit
    try:
        os.sync()
    except AttributeError:
        pass  # os.sync may not be available on all platforms
    logger.info(f"[INGRESS DEBUG] Directory listing after DB commit, before pipeline: {os.listdir(RAW_STORAGE)}")

    _audit(db, "CLAIM_CREATED", claim_id=claim.id, metadata={
        "files": [s for _, _, s in file_data],
        "file_count": len(file_data),
        "upload_sha256": upload_sha256,
        "policy_id": policy_id,
        "patient_id": patient_id,
        "identity_gate": gate_result,
    })

    task_id: str | None = None
    # Auto-trigger Celery OCR→Parser pipeline only when at least one doc passed identity gate.
    if gate_result["accepted_count"] > 0:
        try:
            task_id = _enqueue_pipeline(str(claim.id))
            logger.info("Queued Celery pipeline for claim %s task_id=%s", claim.id, task_id)
        except Exception:
            logger.exception("Failed to enqueue Celery pipeline for claim %s", claim.id)
            raise HTTPException(status_code=503, detail="Claim saved but failed to enqueue background tasks")
    else:
        logger.warning("Claim %s skipped workflow trigger; no documents passed identity gate", claim.id)

    payload = ClaimOut.model_validate(claim).model_dump(mode="json")
    payload["task_id"] = task_id
    return payload


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
    new_docs: list[Document] = []
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
        new_docs.append(doc)

    db.flush()
    gate_result = _apply_identity_gate(db, claim.id, new_docs)
    if gate_result["accepted_count"] == 0:
        claim.status = "MANUAL_REVIEW_REQUIRED"

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
        "identity_gate": gate_result,
    })

    task_id: str | None = None
    # Re-trigger Celery OCR→Parser pipeline only if at least one new document passed identity gate.
    if gate_result["accepted_count"] > 0:
        try:
            task_id = _enqueue_pipeline(str(claim.id))
        except Exception:
            logger.exception("Failed to enqueue Celery pipeline for claim %s", claim.id)
            raise HTTPException(status_code=503, detail="Documents saved but failed to enqueue background tasks")
    else:
        logger.warning("Claim %s no accepted new docs after identity gate; workflow not retriggered", claim.id)

    payload = ClaimOut.model_validate(claim).model_dump(mode="json")
    payload["task_id"] = task_id
    return payload


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
