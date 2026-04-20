
from __future__ import annotations
import os
print(f"[OCR] DATABASE_URL at startup: {os.environ.get('DATABASE_URL')}")

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .doc_validator import validate_claim_documents
from .engine import extract_text
from .models import Claim, Document, DocValidation, OcrJob, OcrResult, ScanAnalysis
from .scan_analyzer import analyze_scan, is_scan_document
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
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("ocr")

app = FastAPI(title="ClaimGPT OCR Service")

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
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
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

    dump_dir = Path(settings.debug_dump_dir)
    if not dump_dir.is_absolute():
        dump_dir = Path.cwd() / dump_dir
    dump_dir.mkdir(parents=True, exist_ok=True)

    docs = (
        db.query(Document)
        .filter(Document.claim_id == claim_id)
        .order_by(Document.uploaded_at)
        .all()
    )

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
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
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

def _run_ocr_job(job_id: uuid.UUID) -> None:
    """
    Process all documents belonging to the job's claim.
    Runs in a BackgroundTasks context so the POST returns immediately.
    """
    logger.info(f"[OCR] _run_ocr_job called for job_id={job_id}")
    db = SessionLocal()
    try:
        job = db.query(OcrJob).filter(OcrJob.id == job_id).first()
        if not job:
            logger.error("OcrJob %s not found — aborting", job_id)
            return
        logger.info(f"[OCR] Job found: {job}")
        job.status = "PROCESSING"
        db.commit()

        claim = db.query(Claim).filter(Claim.id == job.claim_id).first()
        if claim:
            claim.status = "OCR_PROCESSING"
            db.commit()

        excluded_doc_ids = _identity_excluded_doc_ids(db, job.claim_id)
        documents = (
            db.query(Document)
            .filter(Document.claim_id == job.claim_id)
            .order_by(Document.uploaded_at)
            .all()
        )
        logger.info(f"[OCR] Found {len(documents)} documents for claim {job.claim_id}")
        documents = [d for d in documents if d.id not in excluded_doc_ids]
        logger.info(f"[OCR] {len(documents)} documents after exclusion for claim {job.claim_id}")

        job.total_documents = len(documents)
        db.commit()

        failed = False
        for doc in documents:
            try:
                logger.info(f"[OCR] Processing document {doc.id} ({doc.file_name})")
                _process_single_document(db, doc)
                job.processed_documents += 1
                db.commit()
            except Exception as e:
                logger.exception(f"OCR failed for document {doc.id}: {e}")
                failed = True

        # ── Document Validation: verify patient relevance ──
        try:
            _validate_documents_for_claim(db, job.claim_id, documents)
        except Exception:
            db.rollback()
            logger.exception("Document validation failed for claim %s — continuing", job.claim_id)

        # Finalise job
        job.status = "FAILED" if failed else "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        if failed:
            job.error_message = "One or more documents failed OCR"

        if claim:
            claim.status = "OCR_FAILED" if failed else "OCR_DONE"

        db.commit()

        try:
            _write_claim_ocr_debug_dump(db, job.claim_id)
        except Exception:
            logger.warning("Failed to write claim-level OCR debug dump for %s", job.claim_id, exc_info=True)

        logger.info("OCR job %s finished — status=%s", job_id, job.status)
        _audit(db, "OCR_COMPLETED" if not failed else "OCR_FAILED", claim_id=job.claim_id, metadata={
            "job_id": str(job_id),
            "documents_processed": job.processed_documents,
            "total_documents": job.total_documents,
        })

    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error in OCR job {job_id}: {e}")
        # Best-effort mark as failed
        try:
            job = db.query(OcrJob).filter(OcrJob.id == job_id).first()
            if job:
                job.status = "FAILED"
                job.error_message = "Internal error"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _process_single_document(db: Session, doc: Document) -> None:
    logger.warning(f"[OCR DEBUG] Entered _process_single_document for doc: {getattr(doc, 'id', doc)}")
    import os
    file_path = Path(doc.minio_path)
    logger.info(f"[OCR] Checking file existence: {file_path}")
    logger.info(f"[OCR] Directory listing: {os.listdir(file_path.parent)}")
    import time
    max_wait = 5
    waited = 0
    while not os.path.exists(file_path) and waited < max_wait:
        logger.warning(f"[OCR DEBUG] Waiting for file: {file_path} (waited {waited}s)")
        logger.warning(f"[OCR DEBUG] Directory listing: {os.listdir(os.path.dirname(file_path))}")
        time.sleep(1)
        waited += 1
    if not os.path.exists(file_path):
        logger.warning(f"[OCR DEBUG] File still not found after {max_wait}s: {file_path}")
        logger.warning(f"[OCR DEBUG] Directory listing: {os.listdir(os.path.dirname(file_path))}")
        raise FileNotFoundError(f"File not found at {file_path}")
    logger.info(f"[OCR] File exists: {file_path}")
    # Delete prior results for idempotency
    db.query(OcrResult).filter(OcrResult.document_id == doc.id).delete()
    db.query(ScanAnalysis).filter(ScanAnalysis.document_id == doc.id).delete()

    pages = extract_text(file_path)

    _write_ocr_debug_dump(doc, pages)

    for page_num, text, confidence in pages:
        db.add(OcrResult(
            document_id=doc.id,
            page_number=page_num,
            text=text,
            confidence=confidence,
        ))

    db.commit()
    logger.info("OCR ✓ document %s — %d page(s)", doc.id, len(pages))
    _audit(db, "DOCUMENT_OCR_EXTRACTED", claim_id=doc.claim_id, metadata={
        "document_id": str(doc.id),
        "file_name": doc.file_name,
        "pages_extracted": len(pages),
        "original_file_preserved": True,
    })

    # ── Medical scan detection & analysis ──
    full_text = " ".join(t for _, t, _ in pages if t)
    try:
        if is_scan_document(doc.file_name, full_text):
            result = analyze_scan(doc.file_name, full_text, str(file_path))
            if result:
                db.add(ScanAnalysis(
                    document_id=doc.id,
                    claim_id=doc.claim_id,
                    scan_type=result.scan_type,
                    body_part=result.body_part,
                    modality=result.modality,
                    findings=[{"finding": f.finding, "severity": f.severity, "confidence": f.confidence} for f in result.findings],
                    impression=result.impression,
                    recommendation=result.recommendation,
                    confidence=result.confidence,
                    scan_metadata={
                        "scan_type_full": result.scan_type_full,
                        "is_abnormal": result.is_abnormal,
                        "file_name": doc.file_name,
                    },
                ))
                db.commit()
                logger.info("Scan analysis ✓ document %s — type=%s, body=%s, findings=%d",
                            doc.id, result.scan_type, result.body_part, len(result.findings))
                _audit(db, "SCAN_ANALYZED", claim_id=doc.claim_id, metadata={
                    "document_id": str(doc.id),
                    "scan_type": result.scan_type,
                    "body_part": result.body_part,
                    "findings_count": len(result.findings),
                    "is_abnormal": result.is_abnormal,
                })
    except Exception:
        logger.exception("Scan analysis failed for document %s — continuing", doc.id)


def _validate_documents_for_claim(
    db: Session, claim_id: uuid.UUID, documents: list[Document],
) -> None:
    """
    Run cross-document validation: medical relevance + patient identity matching.
    Persists results to document_validations table.
    """
    # Gather OCR text for each document
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

    # Run validation
    result = validate_claim_documents(doc_data, str(claim_id))

    # Delete prior validation results for idempotency
    db.query(DocValidation).filter(
        DocValidation.claim_id == claim_id,
        DocValidation.doc_type != "IDENTITY_GATE",
    ).delete(synchronize_session=False)

    # Persist per-document results
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
        "primary_patient": result.primary_patient.name if result.primary_patient else None,
    })


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.get("/validate/{claim_id}", response_model=ClaimValidationOut)
def get_document_validation(claim_id: str, db: Session = Depends(get_db)):
    """
    Return document validation results for a claim.
    Runs validation on-demand if not yet persisted.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Check for existing validation results
    existing = db.query(DocValidation).filter(
        DocValidation.claim_id == cid,
        DocValidation.doc_type != "IDENTITY_GATE",
    ).all()

    if not existing:
        # Run validation now
        documents = db.query(Document).filter(Document.claim_id == cid).all()
        if not documents:
            raise HTTPException(status_code=404, detail="No documents found for claim")
        _validate_documents_for_claim(db, cid, documents)
        existing = db.query(DocValidation).filter(
            DocValidation.claim_id == cid,
            DocValidation.doc_type != "IDENTITY_GATE",
        ).all()

    # Build response
    doc_results: list[DocValidationOut] = []
    valid_count = 0
    invalid_count = 0
    warning_count = 0
    primary_patient: PatientIdentityOut | None = None

    for v in existing:
        patient_out = None
        if v.patient_name or v.patient_id_extracted:
            patient_out = PatientIdentityOut(
                name=v.patient_name,
                patient_id=v.patient_id_extracted,
            )
        if v.status == "VALID":
            valid_count += 1
        elif v.status == "INVALID":
            invalid_count += 1
        else:
            warning_count += 1

        # Use first valid patient as primary
        if not primary_patient and v.patient_name:
            primary_patient = PatientIdentityOut(
                name=v.patient_name,
                patient_id=v.patient_id_extracted,
            )

        doc_results.append(DocValidationOut(
            document_id=v.document_id,
            file_name="",  # Will be enriched below
            status=v.status,
            doc_type=v.doc_type,
            doc_type_label=v.doc_type_label,
            is_medical=bool(v.is_medical),
            patient_match=v.patient_match,
            confidence=v.confidence,
            issues=v.issues or [],
            patient_identity=patient_out,
        ))

    # Enrich file_name from documents table
    doc_names = {
        d.id: d.file_name
        for d in db.query(Document).filter(Document.claim_id == cid).all()
    }
    for dr in doc_results:
        dr.file_name = doc_names.get(dr.document_id, "")

    overall_status = "INVALID" if invalid_count > 0 else ("WARNING" if warning_count > 0 else "VALID")

    return ClaimValidationOut(
        claim_id=cid,
        status=overall_status,
        total_documents=len(doc_results),
        valid_count=valid_count,
        invalid_count=invalid_count,
        warning_count=warning_count,
        primary_patient=primary_patient,
        documents=doc_results,
        issues=[f"{invalid_count} document(s) failed validation"] if invalid_count > 0 else [],
    )


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
