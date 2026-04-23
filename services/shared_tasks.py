from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from libs.shared.celery_app import celery_app
from libs.utils.audit import AuditLogger
from libs.shared.models import Claim, OcrJob, ParseJob

from services.coding.app.db import SessionLocal as CodingSessionLocal
from services.coding.app.main import run_coding
from services.ocr.app.db import SessionLocal as OcrSessionLocal
from services.ocr.app.main import _run_ocr_job
from services.parser.app.db import SessionLocal as ParserSessionLocal
from services.parser.app.main import _run_parse_job
from services.predictor.app.db import SessionLocal as PredictorSessionLocal
from services.predictor.app.main import run_prediction
from services.validator.app.db import SessionLocal as ValidatorSessionLocal
from services.validator.app.main import run_validation


def _claim_id_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict) and payload.get("claim_id"):
        return str(payload["claim_id"])
    raise ValueError("Task payload did not include claim_id")


def _run_coding_job(claim_id: str) -> None:
    db = CodingSessionLocal()
    try:
        run_coding(claim_id, db=db)
    finally:
        db.close()


def _run_risk_job(claim_id: str) -> None:
    db = PredictorSessionLocal()
    try:
        run_prediction(claim_id, db=db)
    finally:
        db.close()


def _run_validator_job(claim_id: str) -> dict[str, Any]:
    db = ValidatorSessionLocal()
    try:
        result = run_validation(claim_id, db=db)
        cid = uuid.UUID(claim_id)
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            raise ValueError(f"Claim not found during finalization: {claim_id}")

        total_processing_seconds: float | None = None
        if claim.created_at:
            total_processing_seconds = max(
                0.0,
                (datetime.now(UTC) - claim.created_at).total_seconds(),
            )

        claim.status = "COMPLETED"
        db.commit()

        try:
            AuditLogger(db, "workflow").log(
                "PIPELINE_COMPLETED",
                claim_id=cid,
                metadata={
                    "validation_status": result.status,
                    "validation_failed": result.failed,
                    "validation_warnings": result.warnings,
                    "total_processing_seconds": total_processing_seconds,
                },
            )
        except Exception:
            # Do not fail final claim completion if audit insert has issues.
            pass

        return {
            "claim_id": claim_id,
            "validation_status": result.status,
            "total_processing_seconds": total_processing_seconds,
        }
    finally:
        db.close()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def ocr_task(self, claim_id: str) -> dict[str, str]:
    import logging
    logging.getLogger("ocr").info(f"[Celery] ocr_task called for claim_id={claim_id}")
    cid = uuid.UUID(claim_id)
    db = OcrSessionLocal()
    job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            raise ValueError(f"Claim not found: {claim_id}")

        job = OcrJob(claim_id=cid, status="QUEUED")
        db.add(job)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(job)
        job_id = job.id
        logging.getLogger("ocr").info(f"[Celery] Created OcrJob with job_id={job_id} for claim_id={claim_id}")
    finally:
        db.close()

    logging.getLogger("ocr").info(f"[Celery] Calling _run_ocr_job(job_id={job_id})")
    _run_ocr_job(job_id)
    return {"claim_id": claim_id, "ocr_job_id": str(job_id)}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def parser_task(self, claim_id: str) -> dict[str, str]:
    import logging
    logging.getLogger("parser-debug").info(f"[Celery] parser_task called for claim_id={claim_id}")
    claim_id = _claim_id_from_payload(claim_id)
    cid = uuid.UUID(claim_id)
    db = ParserSessionLocal()
    job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            raise ValueError(f"Claim not found: {claim_id}")

        job = ParseJob(claim_id=cid, status="QUEUED")
        db.add(job)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(job)
        job_id = job.id
        logging.getLogger("parser-debug").info(f"[Celery] Created ParseJob with job_id={job_id} for claim_id={claim_id}")
    finally:
        db.close()

    logging.getLogger("parser-debug").info(f"[Celery] Calling _run_parse_job(job_id={job_id})")
    _run_parse_job(job_id)
    return {"claim_id": claim_id, "parse_job_id": str(job_id)}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def coding_task(self, payload: Any) -> dict[str, str]:
    claim_id = _claim_id_from_payload(payload)
    cid = uuid.UUID(claim_id)
    db = CodingSessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            raise ValueError(f"Claim not found: {claim_id}")
    finally:
        db.close()

    _run_coding_job(claim_id)
    return {"claim_id": claim_id, "coding": "DONE"}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def risk_task(self, payload: Any) -> dict[str, str]:
    claim_id = _claim_id_from_payload(payload)
    cid = uuid.UUID(claim_id)
    db = PredictorSessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            raise ValueError(f"Claim not found: {claim_id}")
    finally:
        db.close()

    _run_risk_job(claim_id)
    return {"claim_id": claim_id, "risk": "DONE"}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def validator_task(self, payload: Any) -> dict[str, Any]:
    claim_id = _claim_id_from_payload(payload)
    return _run_validator_job(claim_id)
