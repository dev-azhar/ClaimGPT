from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, engine, check_db_health
from .models import Claim, Document, OcrResult, OcrJob, ScanAnalysis
from .schemas import OcrJobOut, OcrJobStatusOut, OcrDocumentOut, OcrPageOut
from .engine import extract_text
from .scan_analyzer import is_scan_document, analyze_scan

# ── audit helper ──
try:
    import sys as _sys, os as _os
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
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from libs.observability.tracing import init_tracing, instrument_fastapi
    from libs.observability.metrics import init_metrics, PrometheusMiddleware, metrics_endpoint
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


# ------------------------------------------------------------------ background worker

def _run_ocr_job(job_id: uuid.UUID) -> None:
    """
    Process all documents belonging to the job's claim.
    Runs in a BackgroundTasks context so the POST returns immediately.
    """
    db = SessionLocal()
    try:
        job = db.query(OcrJob).filter(OcrJob.id == job_id).first()
        if not job:
            logger.error("OcrJob %s not found — aborting", job_id)
            return

        job.status = "PROCESSING"
        db.commit()

        claim = db.query(Claim).filter(Claim.id == job.claim_id).first()
        if claim:
            claim.status = "OCR_PROCESSING"
            db.commit()

        documents = (
            db.query(Document)
            .filter(Document.claim_id == job.claim_id)
            .order_by(Document.uploaded_at)
            .all()
        )

        job.total_documents = len(documents)
        db.commit()

        failed = False
        for doc in documents:
            try:
                _process_single_document(db, doc)
                job.processed_documents += 1
                db.commit()
            except Exception:
                logger.exception("OCR failed for document %s", doc.id)
                failed = True

        # Finalise job
        job.status = "FAILED" if failed else "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        if failed:
            job.error_message = "One or more documents failed OCR"

        if claim:
            claim.status = "OCR_FAILED" if failed else "OCR_DONE"

        db.commit()
        logger.info("OCR job %s finished — status=%s", job_id, job.status)
        _audit(db, "OCR_COMPLETED" if not failed else "OCR_FAILED", claim_id=job.claim_id, metadata={
            "job_id": str(job_id),
            "documents_processed": job.processed_documents,
            "total_documents": job.total_documents,
        })

    except Exception:
        db.rollback()
        logger.exception("Unexpected error in OCR job %s", job_id)
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
    """Run OCR on one document and persist results."""
    file_path = Path(doc.minio_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found at {file_path}")

    logger.info("OCR → document %s (%s)", doc.id, doc.file_name)

    # Delete prior results for idempotency
    db.query(OcrResult).filter(OcrResult.document_id == doc.id).delete()

    pages = extract_text(file_path)

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
                # Remove prior scan analysis for idempotency
                db.query(ScanAnalysis).filter(ScanAnalysis.document_id == doc.id).delete()
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


# ------------------------------------------------------------------ routes

router = APIRouter()


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

    docs = db.query(Document).filter(Document.claim_id == cid).all()
    if not docs:
        raise HTTPException(status_code=404, detail="No documents found for claim")

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
        documents = db.query(Document).filter(Document.claim_id == job.claim_id).all()
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

    docs = db.query(Document).filter(Document.claim_id == cid).all()
    if not docs:
        raise HTTPException(status_code=404, detail="No documents found for claim")

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
