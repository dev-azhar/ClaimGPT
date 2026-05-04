from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
import asyncio
from libs.shared.celery_app import celery_app
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from libs.utils.audit import AuditLogger
from libs.shared.models import Claim, OcrJob, ParseJob, WorkflowState

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


def _update_workflow_state(claim_id: str, current_step: str, status: str | None = None) -> None:
    import logging
    logging.getLogger("workflow_state").info(f"[WorkflowState] Updating claim_id={claim_id}, current_step={current_step}, status={status}")
    cid = uuid.UUID(claim_id)
    db = OcrSessionLocal()
    try:
        state = db.query(WorkflowState).filter(WorkflowState.claim_id == cid).first()
        if not state:
            state = WorkflowState(
                claim_id=cid,
                current_step=current_step,
                status=status or "RUNNING",
            )
            db.add(state)
            logging.getLogger("workflow_state").info(f"[WorkflowState] Created new state for claim_id={claim_id}")
        else:
            state.current_step = current_step
            if status:
                state.status = status
            logging.getLogger("workflow_state").info(f"[WorkflowState] Updated existing state for claim_id={claim_id}")
        try:
            db.commit()
            logging.getLogger("workflow_state").info(f"[WorkflowState] Committed state: step={current_step}, status={state.status}")
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()


def _mark_job_failed(job_id: uuid.UUID, error_msg: str, db_session_local) -> None:
    """Mark an OCR or Parser job as FAILED with error details."""
    import logging
    logger = logging.getLogger("workflow_state")
    db = db_session_local()
    try:
        # Try to mark as OcrJob first
        ocr_job = db.query(OcrJob).filter(OcrJob.id == job_id).first()
        if ocr_job:
            ocr_job.status = "FAILED"
            ocr_job.error_message = error_msg
            logger.info(f"[OCRJob] Marked job {job_id} as FAILED: {error_msg}")
        
        # Try to mark as ParseJob
        parse_job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if parse_job:
            parse_job.status = "FAILED"
            parse_job.error_message = error_msg
            logger.info(f"[ParseJob] Marked job {job_id} as FAILED: {error_msg}")
        
        if ocr_job or parse_job:
            db.commit()
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as failed: {e}")
        db.rollback()
    finally:
        db.close()


def _run_coding_job(claim_id: str) -> None:
    db = CodingSessionLocal()
    try:
        if asyncio.iscoroutinefunction(run_coding):
            asyncio.run(run_coding(claim_id, db=db))
        else:
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
        return {
            "claim_id": claim_id,
            "validation_status": result.status,
            "validation_failed": result.failed,
            "validation_warnings": result.warnings,
        }
    finally:
        db.close()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=900,  # 15 minutes for OCR (includes Paddle/Tesseract inference)
    time_limit=1200,      # 20 minutes hard limit (safety margin for cleanup)
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
        _update_workflow_state(claim_id, "OCR_IN_PROGRESS", status="RUNNING")
    finally:
        db.close()

    try:
        logging.getLogger("ocr").info(f"[Celery] Calling _run_ocr_job(job_id={job_id})")
        _run_ocr_job(job_id)
        _update_workflow_state(claim_id, "OCR_COMPLETED", status="RUNNING")
        return {"claim_id": claim_id, "ocr_job_id": str(job_id)}
    except SoftTimeLimitExceeded:
        error_msg = "OCR task exceeded time limit (timeout). Marked as failed. Please retry."
        logging.getLogger("ocr").warning(f"[Celery] OCR task timed out for claim_id={claim_id}")
        if job_id:
            _mark_job_failed(job_id, error_msg, OcrSessionLocal)
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        raise ValueError(error_msg)
    except Exception as exc:
        error_type = type(exc).__name__
        if self.request.retries >= self.max_retries:
            error_msg = f"OCR failed after {self.max_retries} retries: {error_type}"
            logging.getLogger("ocr").error(f"[Celery] OCR task exhausted retries for claim_id={claim_id}: {exc}")
            if job_id:
                _mark_job_failed(job_id, error_msg, OcrSessionLocal)
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=300,  # 5 minutes for parsing
    time_limit=400,       # 6m40s hard limit
)
def parser_task(self, result: dict) -> dict[str, str]:
    claim_id = result["claim_id"]
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
        _update_workflow_state(claim_id, "PARSING_IN_PROGRESS", status="RUNNING")
    finally:
        db.close()

    try:
        logging.getLogger("parser-debug").info(f"[Celery] Calling _run_parse_job(job_id={job_id})")
        _run_parse_job(job_id)
        _update_workflow_state(claim_id, "PARSING_COMPLETED", status="RUNNING")
        return {"claim_id": claim_id, "parse_job_id": str(job_id)}
    except SoftTimeLimitExceeded:
        error_msg = "Parser task exceeded time limit (timeout). Marked as failed. Please retry."
        logging.getLogger("parser-debug").warning(f"[Celery] Parser task timed out for claim_id={claim_id}")
        if job_id:
            _mark_job_failed(job_id, error_msg, ParserSessionLocal)
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        raise ValueError(error_msg)
    except Exception as exc:
        error_type = type(exc).__name__
        if self.request.retries >= self.max_retries:
            error_msg = f"Parser failed after {self.max_retries} retries: {error_type}"
            logging.getLogger("parser-debug").error(f"[Celery] Parser task exhausted retries for claim_id={claim_id}: {exc}")
            if job_id:
                _mark_job_failed(job_id, error_msg, ParserSessionLocal)
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=600,  # 10 minutes for coding analysis
    time_limit=800,       # 13m20s hard limit
)
def coding_task(self, payload: Any) -> dict[str, str]:
    claim_id = _claim_id_from_payload(payload)
    _update_workflow_state(claim_id, "CODING_ANALYSIS", status="RUNNING")

    try:
        _run_coding_job(claim_id)
        _update_workflow_state(claim_id, "CODING_COMPLETED", status="RUNNING")
        return {"claim_id": claim_id, "coding": "DONE"}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=600,  # 10 minutes for risk prediction
    time_limit=800,       # 13m20s hard limit
)
def risk_task(self, payload: Any) -> dict[str, str]:
    claim_id = _claim_id_from_payload(payload)
    _update_workflow_state(claim_id, "RISK_ANALYSIS", status="RUNNING")

    try:
        _run_risk_job(claim_id)
        _update_workflow_state(claim_id, "RISK_COMPLETED", status="RUNNING")
        return {"claim_id": claim_id, "risk": "DONE"}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=300,  # 5 minutes for validation
    time_limit=400,       # 6m40s hard limit
)
def validator_task(self, payload: Any) -> dict[str, Any]:
    claim_id = _claim_id_from_payload(payload)
    _update_workflow_state(claim_id, "VALIDATION_RUNNING", status="RUNNING")
    try:
        result = _run_validator_job(claim_id)
        _update_workflow_state(claim_id, "VALIDATION_COMPLETED", status="RUNNING")
        return result
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def finalize_claim_task(self, results: list[Any], claim_id: str, *args: Any) -> dict[str, Any]:
    claim_id = _claim_id_from_payload(claim_id)
    _update_workflow_state(claim_id, "FINALIZING", status="RUNNING")
    cid = uuid.UUID(claim_id)
    db = ValidatorSessionLocal()
    try:
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
        _update_workflow_state(claim_id, "FINISHED", status="FINISHED")
        db.commit()

        try:
            AuditLogger(db, "workflow").log(
                "PIPELINE_COMPLETED",
                claim_id=cid,
                metadata={
                    "final_results": results,
                    "total_processing_seconds": total_processing_seconds,
                },
            )
        except Exception:
            pass

        return {
            "claim_id": claim_id,
            "status": "COMPLETED",
            "total_processing_seconds": total_processing_seconds,
            "results": results,
        }
    finally:
        db.close()
