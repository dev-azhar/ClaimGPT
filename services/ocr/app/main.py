
from __future__ import annotations

# Set-based idempotency: calculate set hash for all documents in a claim
def calculate_claim_documents_set_hash(db: Session, claim_id: uuid.UUID) -> str:
    """
    Fetch all content_hash values for documents linked to a claim, sort, join, and hash them.
    Returns the set hash (SHA-256) for the claim's documents.
    """
    hashes = [d.content_hash for d in db.query(Document).filter(Document.claim_id == claim_id).all() if d.content_hash]
    return calculate_claim_set_hash(hashes)

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from libs.shared.db import get_db_session
from .doc_validator import validate_claim_documents
from .engine import extract_text
from .models import Claim, Document, DocValidation, OcrJob, OcrResult, ScanAnalysis
from .scan_analyzer import analyze_scan, assess_scan_quality, is_scan_document
from libs.utils.idempotency import calculate_sha256, calculate_claim_set_hash
from .schemas import (
    ClaimValidationOut,
    DocValidationOut,
    OcrDocumentOut,
    OcrJobOut,
    OcrJobStatusOut,
    OcrPageOut,
    PatientIdentityOut,
)

# ── audit helper ──
try:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
    from libs.utils.audit import AuditLogger
except Exception:
    AuditLogger = None  # type: ignore

def _audit(db, action, claim_id=None, metadata=None):
    try:
        if AuditLogger:
            AuditLogger(db, "ocr").log(action, claim_id=claim_id, metadata=metadata)
    except Exception:
        pass

# ------------------------------------------------------------------ logging
import sys
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("ocr")
for handler in logging.root.handlers:
    if hasattr(handler, 'stream'):
        handler.setLevel(logging.DEBUG)
        # Ensure immediate flush on every log record
        class FlushingFormatter(logging.Formatter):
            def format(self, record):
                result = super().format(record)
                if hasattr(handler, 'stream'):
                    handler.stream.flush()
                return result
        handler.setFormatter(FlushingFormatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
        ))

app = FastAPI(title="ClaimGPT OCR Service")


class OcrRejectedError(RuntimeError):
    """Raised when OCR rejects a document before or after extraction."""

    def __init__(self, message: str, *, document_id: str | None = None):
        super().__init__(message)
        self.document_id = document_id

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
    init_tracing("ocr")
    init_metrics("ocr")
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


def _render_table_markdown(header: list[str] | None, rows: list[list[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(header or []), *(len(r) for r in rows))
    safe_header = list(header or [])
    while len(safe_header) < col_count:
        safe_header.append(f"col_{len(safe_header) + 1}")

    out_lines = [
        "| " + " | ".join(str(c).strip() for c in safe_header) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for row in rows:
        padded = [str(c).strip() for c in row] + [""] * (col_count - len(row))
        out_lines.append("| " + " | ".join(padded[:col_count]) + " |")
    return "\n".join(out_lines)


def _extract_pdf_tables_for_debug(doc: Document) -> dict[int, list[dict[str, Any]]]:
    if doc.file_type != "application/pdf" or not doc.minio_path:
        return {}

    try:
        import pdfplumber
    except Exception:
        return {}

    page_tables: dict[int, list[dict[str, Any]]] = {}
    try:
        with pdfplumber.open(doc.minio_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                rendered: list[dict[str, Any]] = []
                for t_idx, table in enumerate(tables, start=1):
                    cleaned_rows = [
                        [str(c or "").strip() for c in row]
                        for row in (table or [])
                        if row and any(str(c or "").strip() for c in row)
                    ]
                    if len(cleaned_rows) < 2:
                        continue
                    header = cleaned_rows[0]
                    data_rows = cleaned_rows[1:]
                    rendered.append({
                        "table_index": t_idx,
                        "header": header,
                        "rows": data_rows,
                        "row_count": len(data_rows),
                        "markdown": _render_table_markdown(header, data_rows),
                    })
                if rendered:
                    page_tables[page_idx] = rendered
    except Exception:
        logger.warning("Failed extracting PDF tables for OCR debug: %s", doc.id, exc_info=True)
        return {}

    return page_tables


def _write_ocr_debug_dump(doc: Document, pages: list[tuple[int, str, float | None]]) -> None:
    if not settings.debug_dump_enabled:
        return

    dump_dir = Path(settings.debug_dump_dir)
    if not dump_dir.is_absolute():
        dump_dir = Path.cwd() / dump_dir
    dump_dir.mkdir(parents=True, exist_ok=True)

    page_tables = _extract_pdf_tables_for_debug(doc)

    payload = {
        "claim_id": str(doc.claim_id),
        "document_id": str(doc.id),
        "file_name": doc.file_name,
        "file_type": doc.file_type,
        "source_file_path": doc.minio_path,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "ocr_pages": [
            {
                "page_number": page_num,
                "raw_text": text,
                "detected_tables": page_tables.get(page_num, []),
                "coordinates": [],
                "confidence": confidence,
                "char_count": len(text or ""),
            }
            for page_num, text, confidence in pages
        ],
    }

    file_path = dump_dir / f"{doc.claim_id}_{doc.id}.json"
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _write_claim_ocr_debug_dump(db: Session, claim_id: uuid.UUID) -> None:
    if not settings.debug_dump_enabled:
        return


def _reject_low_quality_scan(doc: Document, file_path: Path) -> str | None:
    """Return a rejection message when the uploaded scan is too blurry or too low-resolution."""
    quality = assess_scan_quality(str(file_path))
    logger.info(
        "Quality check for document %s: acceptable=%s score=%.2f reason=%s size=%sx%s blur=%s",
        doc.id,
        quality.is_acceptable,
        quality.score,
        quality.reason,
        quality.width or "?",
        quality.height or "?",
        f"{quality.blur_score:.2f}" if quality.blur_score is not None else "?",
    )
    if quality.is_acceptable:
        return None

    min_side = f"{quality.width}x{quality.height}" if quality.width and quality.height else "unknown size"
    return (
        "Image quality is too low for reliable extraction. "
        f"Detected {min_side}, quality={quality.score:.2f}, reason={quality.reason}. "
        "Please upload a clearer image or a higher-quality PDF scan."
    )


def _reject_unusable_ocr(doc: Document, pages: list[tuple[int, str, float | None]]) -> str | None:
    """Reject scans that OCR can read only as trivial or near-empty text."""
    non_empty = [text.strip() for _, text, _ in pages if text and text.strip()]
    if not non_empty:
        return "OCR produced no readable text. Please upload a clearer scan or higher-quality PDF."

    joined = " ".join(non_empty)
    char_count = len(re.sub(r"\s+", "", joined))
    word_count = len(re.findall(r"\b\w+\b", joined))
    if char_count < 25 or word_count < 4:
        return (
            "OCR found too little readable content to trust. "
            "Please upload a clearer scan or higher-quality PDF."
        )

    if len(non_empty) == 1 and len(non_empty[0]) < 40:
        return (
            "OCR extracted only a trivial amount of text from the document. "
            "Please upload a clearer scan or higher-quality PDF."
        )

    return None

    documents_payload = []
    for doc in docs:
        rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        page_tables = _extract_pdf_tables_for_debug(doc)
        documents_payload.append({
            "document_id": str(doc.id),
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "source_file_path": doc.minio_path,
            "ocr_pages": [
                {
                    "page_number": r.page_number,
                    "raw_text": r.text or "",
                    "detected_tables": page_tables.get(r.page_number, []),
                    "confidence": r.confidence,
                    "char_count": len(r.text or ""),
                }
                for r in rows
            ],
        })

    payload = {
        "claim_id": str(claim_id),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "document_count": len(documents_payload),
        "documents": documents_payload,
    }

    file_path = dump_dir / f"{claim_id}_ALL.json"
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _identity_excluded_doc_ids(db: Session, claim_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        db.query(DocValidation)
        .filter(
            DocValidation.claim_id == claim_id,
            DocValidation.doc_type == "IDENTITY_GATE",
        )
        .all()
    )
    excluded: set[uuid.UUID] = set()
    for row in rows:
        md = row.validation_metadata or {}
        if md.get("excluded_from_pipeline"):
            excluded.add(row.document_id)
    return excluded


# ------------------------------------------------------------------ background worker

def _run_ocr_job(job_id: uuid.UUID) -> dict[str, str]:
    logger.info(f"[OCR] _run_ocr_job called for job_id={job_id}")
    
    with get_db_session() as db:
        try:
            # Capture IDs early as strings to prevent lazy-loading crashes
            target_job_id = str(job_id)
            job = db.query(OcrJob).get(job_id)
            if not job:
                logger.error("OcrJob %s not found", target_job_id)
                return

            target_claim_id = str(job.claim_id)
            job.status = "PROCESSING"
            
            claim = db.query(Claim).get(job.claim_id)
            if claim:
                claim.status = "OCR_PROCESSING"
            
            # Use flush() to send data to DB without ending the transaction
            db.flush()


            excluded_doc_ids = _identity_excluded_doc_ids(db, job.claim_id)
            documents = db.query(Document).filter(Document.claim_id == job.claim_id).all()

            # Idempotency: skip duplicate content_hash docs
            seen_hashes = set()
            valid_docs = []
            for d in documents:
                if d.id in excluded_doc_ids:
                    continue
                if hasattr(d, "content_hash") and d.content_hash:
                    if d.content_hash in seen_hashes:
                        logger.info(f"[OCR] Skipping duplicate document {d.id} (content_hash={d.content_hash})")
                        continue
                    seen_hashes.add(d.content_hash)
                valid_docs.append(d)

            job.total_documents = len(valid_docs)
            db.flush()

            failed_in_loop = False
            rejected_reason: str | None = None
            for doc in valid_docs:
                current_doc_id = str(doc.id)
                try:
                    logger.info(f"[OCR] Processing document {current_doc_id}")
                    _process_single_document(db, doc)

                    # Refresh job to ensure we are working with a clean object
                    job = db.query(OcrJob).get(target_job_id)
                    job.processed_documents += 1
                    db.flush()
                except OcrRejectedError as e:
                    db.rollback()
                    logger.warning(f"OCR rejected document {current_doc_id}: {e}")
                    rejected_reason = str(e)
                    failed_in_loop = True
                    job = db.query(OcrJob).get(target_job_id)
                    claim = db.query(Claim).get(target_claim_id)
                    break
                except Exception as e:
                    db.rollback()  # Clear the session failure
                    logger.error(f"OCR failed for document {current_doc_id}: {e}")
                    failed_in_loop = True
                    # Re-fetch objects after rollback
                    job = db.query(OcrJob).get(target_job_id)
                    claim = db.query(Claim).get(target_claim_id)

            # Finalize Job Status
            if rejected_reason:
                job.status = "REJECTED"
                job.error_message = rejected_reason
                if claim:
                    claim.status = "OCR_REJECTED"
                db.commit()
                logger.info(f"OCR job {target_job_id} finished: {job.status}")
                return {"status": "REJECTED", "reason": rejected_reason}

            job.status = "FAILED" if failed_in_loop and job.processed_documents == 0 else "COMPLETED"
            if failed_in_loop:
                job.status = "PARTIAL_SUCCESS" if job.processed_documents > 0 else "FAILED"
                job.error_message = "One or more documents failed"

            if claim:
                claim.status = "OCR_DONE" if not failed_in_loop else "OCR_PARTIAL"

            db.commit() # THE ONLY COMMIT THAT MATTERS
            logger.info(f"OCR job {target_job_id} finished: {job.status}")
            return {"status": job.status or "COMPLETED"}

        except Exception as e:
            db.rollback()
            logger.exception(f"Fatal error in OCR job {job_id}")
            return {"status": "FAILED", "reason": str(e)}


def _process_single_document(db: Session, doc: Document) -> None:
    import os, json
    # Use local variables
    doc_id = str(doc.id)
    claim_id = str(doc.claim_id)
    file_path = Path(doc.minio_path)

    # Idempotency: skip if OcrResult already exists for this document (by content_hash)
    existing_ocr = db.query(OcrResult).join(Document, OcrResult.document_id == Document.id)
    if hasattr(doc, "content_hash") and doc.content_hash:
        existing_ocr = existing_ocr.filter(Document.content_hash == doc.content_hash)
    else:
        # fallback to document id if hash missing
        existing_ocr = existing_ocr.filter(OcrResult.document_id == doc_id)
    if existing_ocr.first():
        logger.info(f"[OCR] Skipping document {doc_id} (content_hash={getattr(doc, 'content_hash', None)}) -- OCR result already exists.")
        return

    # Remove any previous results for this doc (should be rare)
    db.query(OcrResult).filter(OcrResult.document_id == doc_id).delete()
    db.query(ScanAnalysis).filter(ScanAnalysis.document_id == doc_id).delete()

    reject_reason = _reject_low_quality_scan(doc, file_path)
    if reject_reason:
        logger.warning("Rejecting low-quality scan for document %s: %s", doc_id, reject_reason)
        _audit(db, "OCR_REJECTED_LOW_QUALITY", claim_id=doc.claim_id, metadata={
            "document_id": doc_id,
            "file_name": doc.file_name,
            "reason": reject_reason,
        })
        db.add(ScanAnalysis(
            document_id=doc_id,
            claim_id=claim_id,
            scan_type="Unknown",
            body_part="",
            modality="",
            findings=[],
            impression=reject_reason,
            recommendation="Upload a clearer scan or higher-resolution PDF.",
            confidence=0.0,
        ))
        db.flush()
        raise OcrRejectedError(reject_reason, document_id=doc_id)

    # Core OCR
    pages = extract_text(file_path)
    unusable_reason = _reject_unusable_ocr(doc, pages)
    if unusable_reason:
        logger.warning("Rejecting unreadable OCR for document %s: %s", doc_id, unusable_reason)
        _audit(db, "OCR_REJECTED_LOW_QUALITY", claim_id=doc.claim_id, metadata={
            "document_id": doc_id,
            "file_name": doc.file_name,
            "reason": unusable_reason,
        })
        db.add(ScanAnalysis(
            document_id=doc_id,
            claim_id=claim_id,
            scan_type="Unknown",
            body_part="",
            modality="",
            findings=[],
            impression=unusable_reason,
            recommendation="Upload a clearer scan or higher-resolution PDF.",
            confidence=0.0,
        ))
        db.flush()
        raise OcrRejectedError(unusable_reason, document_id=doc_id)

    for page_num, text, confidence in pages:
        db.add(OcrResult(document_id=doc_id, page_number=page_num, text=text, confidence=confidence))
    
    db.flush() # Ensure text is prepared in DB buffer

    # Medical scan analysis (USING NESTED TRANSACTION)
    full_text = " ".join(t for _, t, _ in pages if t)
    if is_scan_document(doc.file_name, full_text):
        result = analyze_scan(doc.file_name, full_text, str(file_path))
        if result:
            # Sanitize JSON
            findings_list = [{"finding": f.finding, "severity": f.severity, "confidence": f.confidence} for f in result.findings]
            findings_json = json.dumps(findings_list).replace('\u0000', '') # Remove null bytes
            
            # Use Savepoint to isolate AI failure
            savepoint = db.begin_nested()
            try:
                db.add(ScanAnalysis(
                    document_id=doc_id, claim_id=claim_id,
                    scan_type=result.scan_type, findings=json.loads(findings_json),
                    impression=result.impression, confidence=result.confidence
                ))
                db.flush()
                savepoint.commit() # Only commits the ScanAnalysis
            except Exception:
                savepoint.rollback() # Discards ONLY the ScanAnalysis
                logger.warning(f"Scan analysis metadata failed for {doc_id} — skipping.")


def _process_single_document_by_id(doc_id: str) -> None:
    """Process one document in its own DB session so OCR can run in parallel."""
    with get_db_session() as thread_db:
        doc = thread_db.query(Document).get(doc_id)
        if not doc:
            raise ValueError(f"Document {doc_id} not found")
        _process_single_document(thread_db, doc)
        thread_db.commit()
                

def _validate_documents_for_claim(
    db: Session, claim_id: uuid.UUID, documents: list[Document],
) -> None:
    """
    Run cross-document validation: medical relevance + patient identity matching.
    Persists results to document_validations table.
    """
    doc_data = []
    for doc in documents:
        rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        full_text = " ".join(r.text for r in rows if r.text)
        doc_data.append({
            "document_id": str(doc.id),
            "file_name": doc.file_name,
            "text": full_text,
        })

    if not doc_data:
        return

    result = validate_claim_documents(doc_data, str(claim_id))

    db.query(DocValidation).filter(
        DocValidation.claim_id == claim_id,
        DocValidation.doc_type != "IDENTITY_GATE",
    ).delete(synchronize_session=False)

    for dv in result.documents:
        db.add(DocValidation(
            document_id=uuid.UUID(dv.document_id),
            claim_id=claim_id,
            status=dv.status,
            doc_type=dv.doc_type,
            doc_type_label=dv.doc_type_label,
            is_medical=1 if dv.is_medical else 0,
            patient_match=dv.patient_match,
            confidence=dv.confidence,
            patient_name=dv.patient_identity.name if dv.patient_identity else None,
            patient_id_extracted=dv.patient_identity.patient_id if dv.patient_identity else None,
            issues=dv.issues,
            validation_metadata={
                "doc_type": dv.doc_type,
                "text_length": dv.metadata.get("text_length", 0),
            },
        ))

    db.commit()
    logger.info(
        "Document validation ✓ claim %s — %d valid, %d invalid, %d warning",
        claim_id, result.valid_count, result.invalid_count, result.warning_count,
    )
    _audit(db, "DOCUMENTS_VALIDATED", claim_id=claim_id, metadata={
        "status": result.status,
        "total_documents": result.total_documents,
        "valid_count": result.valid_count,
        "invalid_count": result.invalid_count,
        "warning_count": result.warning_count,
    })


router = APIRouter(tags=["ocr"])


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.post("/{claim_id}", response_model=OcrJobOut, status_code=202)
def start_ocr(
    claim_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start async OCR for all documents belonging to `claim_id`.
    Returns a job_id that can be polled via GET /ocr/{job_id}.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    excluded_doc_ids = _identity_excluded_doc_ids(db, cid)
    docs = [
        d for d in db.query(Document).filter(Document.claim_id == cid).all()
        if d.id not in excluded_doc_ids
    ]
    if not docs:
        raise HTTPException(status_code=409, detail="No documents passed identity gate for OCR")

    job = OcrJob(
        claim_id=cid,
        status="QUEUED",
        total_documents=len(docs),
        processed_documents=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_ocr_job, job.id)

    return OcrJobOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=job.processed_documents,
        created_at=job.created_at,
    )


@router.get("/job/{job_id}", response_model=OcrJobStatusOut)
def get_ocr_status(job_id: str, db: Session = Depends(get_db)):
    """
    Poll job status. When COMPLETED, `results` contains per-document OCR output.
    """
    jid = _parse_uuid(job_id)

    job = db.query(OcrJob).filter(OcrJob.id == jid).first()
    if not job:
        raise HTTPException(status_code=404, detail="OCR job not found")

    # Build results only when the job is done
    results: list[OcrDocumentOut] = []
    if job.status in ("COMPLETED", "FAILED"):
        excluded_doc_ids = _identity_excluded_doc_ids(db, job.claim_id)
        documents = [
            d for d in db.query(Document).filter(Document.claim_id == job.claim_id).all()
            if d.id not in excluded_doc_ids
        ]
        for doc in documents:
            rows = (
                db.query(OcrResult)
                .filter(OcrResult.document_id == doc.id)
                .order_by(OcrResult.page_number)
                .all()
            )
            pages = [
                OcrPageOut(
                    id=r.id,
                    page_number=r.page_number,
                    text=r.text,
                    confidence=r.confidence,
                    created_at=r.created_at,
                )
                for r in rows
            ]
            if pages:
                results.append(OcrDocumentOut(
                    document_id=doc.id,
                    file_name=doc.file_name,
                    pages=pages,
                    total_pages=len(pages),
                ))

    return OcrJobStatusOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=job.processed_documents,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        results=results,
    )


@router.get("/claim/{claim_id}", response_model=list[OcrDocumentOut])
def get_ocr_results_by_claim(claim_id: str, db: Session = Depends(get_db)):
    """Retrieve OCR results for all documents belonging to a claim."""
    cid = _parse_uuid(claim_id)

    excluded_doc_ids = _identity_excluded_doc_ids(db, cid)
    docs = [
        d for d in db.query(Document).filter(Document.claim_id == cid).all()
        if d.id not in excluded_doc_ids
    ]
    if not docs:
        raise HTTPException(status_code=404, detail="No OCR-eligible documents found for claim")

    result = []
    for doc in docs:
        rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        pages = [
            OcrPageOut(
                id=r.id,
                page_number=r.page_number,
                text=r.text,
                confidence=r.confidence,
                created_at=r.created_at,
            )
            for r in rows
        ]
        result.append(
            OcrDocumentOut(
                document_id=doc.id,
                file_name=doc.file_name,
                pages=pages,
                total_pages=len(pages),
            )
        )

    return result


# ── Include router (standalone mode) ──
app.include_router(router)
