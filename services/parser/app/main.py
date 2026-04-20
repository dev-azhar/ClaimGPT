
from __future__ import annotations
import os
print(f"[PARSER] DATABASE_URL at startup: {os.environ.get('DATABASE_URL')}")

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
from .engine import ParseOutput, parse_document
from .models import Claim, DocValidation, Document, OcrResult, ParsedField, ParseJob
from .schemas import (
    ParsedFieldOut,
    ParseJobOut,
    ParseJobStatusOut,
    ParseResultOut,
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
            AuditLogger(db, "parser").log(action, claim_id=claim_id, metadata=metadata)
    except Exception:
        pass

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("parser-debug")

app = FastAPI(title="ClaimGPT Parser Service")

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
    init_tracing("parser")
    init_metrics("parser")
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


# ------------------------------------------------------------------ helpers

def _gather_ocr_pages(db: Session, claim_id: uuid.UUID) -> list[dict[str, Any]]:
    """Collect OCR text grouped by page for a claim's documents."""
    excluded_doc_ids = {
        r.document_id
        for r in db.query(DocValidation).filter(
            DocValidation.claim_id == claim_id,
            DocValidation.doc_type == "IDENTITY_GATE",
        ).all()
        if (r.validation_metadata or {}).get("excluded_from_pipeline")
    }

    documents = (
        db.query(Document)
        .filter(Document.claim_id == claim_id)
        .order_by(Document.uploaded_at)
        .all()
    )
    documents = [d for d in documents if d.id not in excluded_doc_ids]
    pages: list[dict[str, Any]] = []
    for doc in documents:
        rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        for r in rows:
            pages.append({
                "page_number": r.page_number,
                "text": r.text or "",
                "raw_text": r.text or "",
                "markdown": r.text or "",
                "document_id": str(doc.id),
                "file_name": doc.file_name,
            })
    return pages


def _persist_fields(
    db: Session,
    claim_id: uuid.UUID,
    output: ParseOutput,
) -> None:
    """Delete old parsed fields for claim and insert new ones."""
    db.query(ParsedField).filter(ParsedField.claim_id == claim_id).delete()

    for f in output.fields:
        db.add(ParsedField(
            claim_id=claim_id,
            field_name=f.field_name,
            field_value=f.field_value,
            bounding_box=f.bounding_box,
            source_page=f.source_page,
            model_version=f.model_version,
        ))
    db.commit()


def _render_table_markdown(header: List[Any] | None, rows: List[List[Any]]) -> str:
    if not rows:
        return ""
    col_count = max(len(header or []), *(len(r) for r in rows))
    safe_header = [str(c).strip() for c in (header or [])]
    while len(safe_header) < col_count:
        safe_header.append(f"col_{len(safe_header) + 1}")

    lines = [
        "| " + " | ".join(safe_header) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for row in rows:
        padded = [str(c).strip() for c in row] + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(padded[:col_count]) + " |")
    return "\n".join(lines)


def _build_table_views(output: ParseOutput) -> List[Dict[str, Any]]:
    views: List[Dict[str, Any]] = []

    for idx, table in enumerate(output.tables or [], start=1):
        rows = table.get("rows") or []
        header = table.get("header")
        views.append({
            "source": "parser_output",
            "table_index": idx,
            "source_page": table.get("source_page"),
            "row_count": table.get("row_count", len(rows)),
            "header": header,
            "rows": rows,
            "markdown": _render_table_markdown(header, rows),
        })

    for p in output.page_objects or []:
        page_num = p.get("page_number")
        doc_id = p.get("document_id")
        for idx, table in enumerate(p.get("detected_tables") or [], start=1):
            rows = table.get("rows") or []
            header = table.get("header")
            views.append({
                "source": "page_detected",
                "document_id": doc_id,
                "source_page": page_num,
                "table_index": idx,
                "row_count": table.get("row_count", len(rows)),
                "header": header,
                "rows": rows,
                "markdown": _render_table_markdown(header, rows),
            })

    return views


def _write_parse_debug_dump(
    job: ParseJob,
    ocr_pages: List[Dict[str, Any]],
    output: ParseOutput,
) -> None:
    """Temporarily dump OCR + parsed data for manual inspection/debugging."""
    if not settings.debug_dump_enabled:
        return

    dump_dir = Path(settings.debug_dump_dir)
    if not dump_dir.is_absolute():
        dump_dir = Path.cwd() / dump_dir
    dump_dir.mkdir(parents=True, exist_ok=True)
    table_views = _build_table_views(output)

    payload = {
        "claim_id": str(job.claim_id),
        "job_id": str(job.id),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": output.model_version,
        "used_fallback": output.used_fallback,
        "ocr_pages": ocr_pages,
        "page_objects": output.page_objects,
        "results": output.document_boundaries,
        "fields": [
            {
                "field_name": f.field_name,
                "field_value": f.field_value,
                "bounding_box": f.bounding_box,
                "source_page": f.source_page,
                "model_version": f.model_version,
            }
            for f in output.fields
        ],
        "tables": output.tables,
        "table_views": table_views,
        "sections": output.sections,
    }

    file_name = f"{job.claim_id}_{job.id}.json"
    file_path = dump_dir / file_name
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    logger.info("Parser debug dump written: %s", file_path)


# ------------------------------------------------------------------ background worker

def _run_parse_job(job_id: uuid.UUID) -> None:
    """Background worker that parses all documents for a claim."""
    logger.info(f"[PARSER] _run_parse_job called for job_id={job_id}")
    db = SessionLocal()
    try:
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if not job:
            logger.error("ParseJob %s not found — aborting", job_id)
            return
        logger.info(f"[PARSER] Job found: {job}")

        job.status = "PROCESSING"
        db.commit()

        claim = db.query(Claim).filter(Claim.id == job.claim_id).first()
        if claim:
            claim.status = "PARSING"
            db.commit()

        ocr_pages = _gather_ocr_pages(db, job.claim_id)
        logger.info(f"[PARSER] Found {len(ocr_pages)} OCR pages for claim {job.claim_id}")
        if not ocr_pages:
            job.status = "FAILED"
            job.error_message = "No OCR results available — run OCR first"
            job.completed_at = datetime.now(timezone.utc)
            if claim:
                claim.status = "PARSE_FAILED"
            db.commit()
            logger.warning(f"[PARSER] No OCR pages found for claim {job.claim_id}, job {job_id} failed.")
            return

        job.total_documents = len(
            {p["document_id"] for p in ocr_pages}
        )
        db.commit()

        try:
            output = parse_document(ocr_pages)
        except Exception:
            logger.exception("Parse engine failed for job %s", job_id)
            job.status = "FAILED"
            job.error_message = "Parse engine error"
            job.completed_at = datetime.now(timezone.utc)
            if claim:
                claim.status = "PARSE_FAILED"
            db.commit()
            return

        try:
            _write_parse_debug_dump(job, ocr_pages, output)
        except Exception:
            logger.warning("Failed to write parser debug dump for job %s", job_id, exc_info=True)

        # Guard against out-of-order completion: never let an older job overwrite
        # parsed fields produced by a newer parse job for the same claim.
        latest_job = (
            db.query(ParseJob)
            .filter(ParseJob.claim_id == job.claim_id)
            .order_by(ParseJob.created_at.desc(), ParseJob.id.desc())
            .first()
        )
        if latest_job and latest_job.id != job.id:
            job.status = "COMPLETED"
            job.model_version = output.model_version
            job.used_fallback = output.used_fallback
            job.processed_documents = job.total_documents
            job.error_message = "Superseded by newer parse job; fields not persisted"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                "Parse job %s completed but skipped persistence (superseded by %s)",
                job_id,
                latest_job.id,
            )
            return

        _persist_fields(db, job.claim_id, output)

        job.status = "COMPLETED"
        job.model_version = output.model_version
        job.used_fallback = output.used_fallback
        job.processed_documents = job.total_documents
        job.completed_at = datetime.now(timezone.utc)

        if claim:
            claim.status = "PARSED"

        db.commit()
        logger.info(
            "Parse job %s complete — %d fields extracted (fallback=%s)",
            job_id,
            len(output.fields),
            output.used_fallback,
        )
        _audit(db, "DATA_EXTRACTED_FROM_COPY", claim_id=job.claim_id, metadata={
            "job_id": str(job_id),
            "fields_extracted": len(output.fields),
            "field_names": [f.field_name for f in output.fields],
            "model_version": output.model_version,
            "used_fallback": output.used_fallback,
            "originals_preserved": True,
        })

    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error in parse job {job_id}: {e}")
        try:
            job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
            if job:
                job.status = "FAILED"
                job.error_message = "Internal error"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.post("/parse/{claim_id}", response_model=ParseJobOut, status_code=202)
def start_parse(
    claim_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger document parsing for a claim. Reads OCR results from the DB,
    runs LayoutLMv3 (or heuristic fallback), and persists structured fields.
    Returns a job_id for polling.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Ensure OCR has been run
    excluded_doc_ids = {
        r.document_id
        for r in db.query(DocValidation).filter(
            DocValidation.claim_id == cid,
            DocValidation.doc_type == "IDENTITY_GATE",
        ).all()
        if (r.validation_metadata or {}).get("excluded_from_pipeline")
    }

    doc_ids = [
        d.id for d in db.query(Document).filter(Document.claim_id == cid).all()
        if d.id not in excluded_doc_ids
    ]
    if not doc_ids:
        raise HTTPException(status_code=409, detail="No documents passed identity gate for parsing")

    ocr_count = (
        db.query(OcrResult)
        .filter(OcrResult.document_id.in_(doc_ids))
        .count()
    )
    if ocr_count == 0:
        raise HTTPException(
            status_code=409,
            detail="OCR has not been completed for this claim — run OCR first",
        )

    job = ParseJob(
        claim_id=cid,
        status="QUEUED",
        total_documents=len(doc_ids),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_parse_job, job.id)

    return ParseJobOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=0,
        created_at=job.created_at,
    )


@router.get("/parse/{claim_id}", response_model=ParseResultOut)
def get_parsed(claim_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the latest parsed fields for a claim.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    rows = (
        db.query(ParsedField)
        .filter(ParsedField.claim_id == cid)
        .order_by(ParsedField.source_page, ParsedField.field_name)
        .all()
    )

    # Determine status from latest parse job
    latest_job = (
        db.query(ParseJob)
        .filter(ParseJob.claim_id == cid)
        .order_by(ParseJob.created_at.desc())
        .first()
    )
    status = latest_job.status if latest_job else ("PARSED" if rows else "NOT_STARTED")
    model_version = latest_job.model_version if latest_job else None
    used_fallback = latest_job.used_fallback if latest_job else False

    fields = [
        ParsedFieldOut(
            id=r.id,
            field_name=r.field_name,
            field_value=r.field_value,
            bounding_box=r.bounding_box,
            source_page=r.source_page,
            model_version=r.model_version,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return ParseResultOut(
        claim_id=cid,
        status=status,
        model_version=model_version,
        used_fallback=used_fallback,
        fields=fields,
    )


@router.get("/parse/job/{job_id}", response_model=ParseJobStatusOut)
def get_parse_job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll a parse job for its status and results."""
    jid = _parse_uuid(job_id)

    job = db.query(ParseJob).filter(ParseJob.id == jid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Parse job not found")

    fields: list[ParsedFieldOut] = []
    if job.status in ("COMPLETED", "FAILED"):
        rows = (
            db.query(ParsedField)
            .filter(ParsedField.claim_id == job.claim_id)
            .order_by(ParsedField.source_page, ParsedField.field_name)
            .all()
        )
        fields = [
            ParsedFieldOut(
                id=r.id,
                field_name=r.field_name,
                field_value=r.field_value,
                bounding_box=r.bounding_box,
                source_page=r.source_page,
                model_version=r.model_version,
                created_at=r.created_at,
            )
            for r in rows
        ]

    return ParseJobStatusOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=job.processed_documents,
        model_version=job.model_version,
        used_fallback=job.used_fallback,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        fields=fields,
    )


# ── Include router (standalone mode) ──
app.include_router(router)
