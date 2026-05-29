from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
import asyncio
import hashlib
from pathlib import Path
import shutil
from sqlalchemy import func
from libs.shared.celery_app import celery_app
from celery import shared_task
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from libs.utils.audit import AuditLogger
from libs.shared.models import Claim, OcrJob, ParseJob, WorkflowState, Document
from libs.shared.workflow_state import upsert_workflow_state

from services.coding.app.db import SessionLocal as CodingSessionLocal
from services.coding.app.main import run_coding
# Preload RAG indices, embedding models, and layout analyzer on worker import to avoid
# per-task initialization latency. This runs when Celery imports this
# module (worker startup) so subsequent tasks are faster.
try:
    from services.coding.app.icd10_rag import preload_rag_models
    try:
        preload_rag_models()
    except Exception:
        import logging
        logging.getLogger("workflow_state").warning("Preloading RAG models failed", exc_info=True)
except Exception:
    # If the coding app is not available in this environment, skip preload.
    pass

try:
    from services.parser.app.layout_analyzer import init_pp_structure
    try:
        init_pp_structure()
    except Exception:
        import logging
        logging.getLogger("workflow_state").warning("Preloading layout models failed", exc_info=True)
except Exception:
    # If the parser app is not available in this environment, skip preload.
    pass
from services.ocr.app.db import SessionLocal as OcrSessionLocal
from services.ocr.app.main import _run_ocr_job
from services.parser.app.db import SessionLocal as ParserSessionLocal
from services.parser.app.main import _run_parse_job
from services.predictor.app.db import SessionLocal as PredictorSessionLocal
from services.predictor.app.main import run_prediction
from services.validator.app.db import SessionLocal as ValidatorSessionLocal
from services.validator.app.main import run_validation


class NonRetryableTaskError(Exception):
    """Raised for expected terminal task outcomes that should not be retried."""


def _claim_id_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        if "claim_id" in payload:
            return _claim_id_from_payload(payload["claim_id"])
        if "id" in payload:
            return _claim_id_from_payload(payload["id"])
    raise ValueError("Task payload did not include claim_id")


def _update_workflow_state(claim_id: str, current_step: str, status: str | None = None) -> None:

    import logging
    logging.getLogger("workflow_state").info(f"[WorkflowState] Updating claim_id={claim_id}, current_step={current_step}, status={status}")
    db = OcrSessionLocal()
    try:
        claim_uuid = uuid.UUID(str(claim_id))
        if not db.query(Claim.id).filter(Claim.id == claim_uuid).first():
            logging.getLogger("workflow_state").warning(
                "[WorkflowState] Skipping update for missing claim_id=%s step=%s status=%s",
                claim_id,
                current_step,
                status,
            )
            return

        state = upsert_workflow_state(db, claim_id, current_step, status=status)
        try:
            db.commit()
            logging.getLogger("workflow_state").info(f"[WorkflowState] Committed state: step={current_step}, status={state.status if state else status}")
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


def _is_terminal_coding_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    return (
        isinstance(exc, ValueError)
        and (
            message == "claim not found"
            or message.startswith("no ocr/parsed data available")
            or message.startswith("invalid uuid")
        )
    )


def _is_terminal_task_error(exc: Exception) -> bool:
    """Check if an exception raised in Celery tasks is terminal and should not be retried."""
    if hasattr(exc, "status_code") and exc.status_code in (400, 404):
        return True

    message = str(exc).strip().lower()
    if "claim not found" in message or "invalid uuid" in message or "no ocr/parsed data available" in message:
        return True

    if "foreign key" in message or "violates foreign key constraint" in message or "not present in table" in message:
        return True

    if hasattr(exc, "detail"):
        detail = str(exc.detail).strip().lower()
        if "claim not found" in detail or "invalid uuid" in detail:
            return True

    return False



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
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=900,  # 15 minutes for OCR (includes Paddle/Tesseract inference)
    time_limit=1200,      # 20 minutes hard limit (safety margin for cleanup)
)
def ocr_task(self, result: dict) -> dict[str, str]:
    """OCR task that receives result from intake_task."""
    claim_id = _claim_id_from_payload(result)
    import logging
    logging.getLogger("ocr").info(f"[Celery] ocr_task called for claim_id={claim_id}")
    cid = uuid.UUID(claim_id)
    db = OcrSessionLocal()
    job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            logging.getLogger("ocr").warning(f"[Celery] Claim not found for OCR, skipping task: {claim_id}")
            raise Ignore()

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
        outcome = _run_ocr_job(job_id)
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if status == "REJECTED":
            error_msg = str(outcome.get("reason") or "OCR rejected the document.")
            logging.getLogger("ocr").warning(f"[Celery] OCR rejected claim_id={claim_id}: {error_msg}")
            if job_id:
                _mark_job_failed(job_id, error_msg, OcrSessionLocal)
            _update_workflow_state(claim_id, "OCR_REJECTED", status="FAILED")
            raise Ignore()
        if status == "FAILED":
            error_msg = str(outcome.get("reason") or "OCR failed.")
            if job_id:
                _mark_job_failed(job_id, error_msg, OcrSessionLocal)
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
            raise ValueError(error_msg)
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
        if isinstance(exc, (NonRetryableTaskError, Ignore)):
            raise
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
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    soft_time_limit=300,  # 5 minutes for parsing
    time_limit=400,       # 6m40s hard limit
)
def parser_task(self, result: dict) -> dict[str, str]:
    claim_id = _claim_id_from_payload(result)
    import logging
    logging.getLogger("parser-debug").info(f"[Celery] parser_task called for claim_id={claim_id}")
    cid = uuid.UUID(claim_id)
    db = ParserSessionLocal()
    job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            logging.getLogger("parser-debug").warning(f"[Celery] Claim not found for parser, skipping task: {claim_id}")
            raise Ignore()

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
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
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
        if _is_terminal_coding_error(exc) or _is_terminal_task_error(exc):
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
            raise Ignore() from exc
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
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
        if _is_terminal_task_error(exc):
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
            raise Ignore() from exc
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
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
        if _is_terminal_task_error(exc):
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
            raise Ignore() from exc
        if self.request.retries >= self.max_retries:
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
        else:
            _update_workflow_state(claim_id, "RETRYING", status="RUNNING")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    soft_time_limit=120,
    time_limit=180,
)
def intake_task(
    self,
    file_metadata: list[dict[str, str]],
    policy_id: str | None = None,
    patient_id: str | None = None,
) -> dict[str, str]:
    """
    Intake task: Database operations for claim creation and document persistence.
    Runs BEFORE OCR to handle all idempotency and deduplication logic.
    
    Also relocates files from temporary names to permanent names using claim_id.
    
    Args:
        file_metadata: List of dicts with keys:
            - path: Temporary local file path (pending_*.*)
            - safe_name: Safe filename
            - content_hash: SHA-256 hash of file content
            - effective_ct: Canonical content type
        policy_id: Optional policy ID
        patient_id: Optional patient ID
    
    Returns:
        {"claim_id": claim_id} on success
    
    Raises:
        Ignore if duplicate completed claim found (idempotent)
        ValueError for terminal errors
    """
    import logging
    from pathlib import Path
    import shutil
    logger = logging.getLogger("intake")
    logger.info(f"[Intake] Starting for {len(file_metadata)} files, policy_id={policy_id}, patient_id={patient_id}")
    
    from services.ocr.app.db import SessionLocal as OcrSessionLocal
    
    db = OcrSessionLocal()
    # try:
    #     # --- STEP 2: Create new claim ---
    #     claim = Claim(
    #         policy_id=policy_id,
    #         patient_id=patient_id,
    #         status="UPLOADED",
    #         source="PATIENT",
    #     )
    #     db.add(claim)
    #     db.flush()
    #     claim_id = claim.id
    #     logger.info(f"[Intake] Created claim {claim_id}")

    #     # --- STEP 1: Check for global duplicate by content_hash ---
    #     if len(file_metadata) == 1:
    #         single_hash = file_metadata[0]["content_hash"]
    #         logger.info(f"[Intake] Checking for single-file duplicate with hash={single_hash}")
    #         existing_doc = db.query(Document).filter(Document.content_hash == single_hash).first()
    #         if existing_doc:
    #             existing_claim = existing_doc.claim
    #             logger.info(f"[Intake] Found existing claim {existing_claim.id} with same content hash")
    #             if existing_claim.status == "COMPLETED":
    #                 logger.info(f"[Intake] Claim {existing_claim.id} already completed; returning idempotently")
    #                 raise Ignore()
                
    #             parse_job = (
    #                 db.query(ParseJob)
    #                 .filter(ParseJob.claim_id == existing_claim.id)
    #                 .order_by(ParseJob.created_at.desc())
    #                 .first()
    #             )
    #             if parse_job and parse_job.status in ("PENDING", "IN_PROGRESS", "QUEUED", "PARSING"):
    #                 logger.info(f"[Intake] Claim {existing_claim.id} already in progress")
    #                 raise Ignore()
        
        
    #     # --- STEP 3: Relocate files and create document rows ---
    #     from services.ingress.app.config import settings
    #     RAW_STORAGE = Path(settings.storage_root).resolve()
        
    #     for idx, metadata in enumerate(file_metadata):
    #         safe_name = metadata["safe_name"]
    #         content_hash = metadata["content_hash"]
    #         effective_ct = metadata["effective_ct"]
    #         temp_path = Path(metadata["path"])
            
    #         # Check for duplicate within this claim
    #         duplicate_doc = (
    #             db.query(Document)
    #             .filter(Document.claim_id == claim_id, Document.content_hash == content_hash)
    #             .first()
    #         )
    #         if duplicate_doc:
    #             logger.info(f"[Intake] Skipping duplicate document in same claim: {safe_name}")
    #             # Clean up temp file
    #             try:
    #                 temp_path.unlink(missing_ok=True)
    #             except Exception:
    #                 pass
    #             continue
            
    #         # Generate permanent filename using claim_id
    #         ext = Path(safe_name).suffix or ".bin"
    #         stored_name = f"{claim_id}_{idx}{ext}" if len(file_metadata) > 1 else f"{claim_id}{ext}"
    #         permanent_path = RAW_STORAGE / stored_name
            
    #         # Move file from temp to permanent location
    #         try:
    #             shutil.move(str(temp_path), str(permanent_path))
    #             logger.info(f"[Intake] Moved file: {temp_path} -> {permanent_path}")
    #         except OSError as e:
    #             logger.exception(f"[Intake] Failed to move file: {e}")
    #             # Try to clean up
    #             try:
    #                 temp_path.unlink(missing_ok=True)
    #             except Exception:
    #                 pass
    #             raise ValueError(f"Failed to relocate file {safe_name}: {e}")
            
    #         # Create document row with permanent path
    #         doc = Document(
    #             claim_id=claim_id,
    #             file_name=safe_name,
    #             file_type=effective_ct,
    #             minio_path=str(permanent_path),
    #             content_hash=content_hash,
    #         )
    #         db.add(doc)
    #         logger.info(f"[Intake] Created document {safe_name} for claim {claim_id} at {permanent_path}")
        
    #     db.commit()
    #     logger.info(f"[Intake] Committed claim {claim_id} with {len(file_metadata)} documents")
        
    #     # --- STEP 4: Calculate set_hash for idempotency of multi-file uploads ---
    #     hashes = [d.content_hash for d in db.query(Document).filter(Document.claim_id == claim_id).all() if d.content_hash]
    #     hashes.sort()
    #     import hashlib
    #     set_hash = hashlib.sha256(",".join(hashes).encode("utf-8")).hexdigest()
    #     logger.info(f"[Intake] Calculated set_hash={set_hash} for claim {claim_id}")
        
    #     # Create ParseJob row with set_hash for idempotency checking
    #     parse_job = ParseJob(
    #         claim_id=claim_id,
    #         status="PENDING",
    #         set_hash=set_hash,
    #     )
    #     db.add(parse_job)
    #     db.commit()
        
    #     _update_workflow_state(str(claim_id), "STARTING", status="RUNNING")
        
    #     return {"claim_id": str(claim_id)}
    
    # except Ignore:
    #     raise
    # except Exception as exc:
    #     db.rollback()
    #     logger.exception(f"[Intake] Task failed: {exc}")
    #     if _is_terminal_task_error(exc):
    #         raise Ignore() from exc
    #     if self.request.retries >= self.max_retries:
    #         error_msg = f"Intake task failed after {self.max_retries} retries: {exc}"
    #         logger.error(error_msg)
    #         raise ValueError(error_msg)
    #     else:
    #         raise self.retry(exc=exc)
    # finally:
    #     db.close()
    try:
        # --- STEP 1: Duplicate check BEFORE creating anything ---
        # Only meaningful for single-file uploads; multi-file dedup uses set_hash downstream
        if len(file_metadata) == 1:
            single_hash = file_metadata[0]["content_hash"]
            logger.info(f"[Intake] Checking for single-file duplicate with hash={single_hash}")

            # Single query: join Document → Claim → ParseJob in one round-trip
            row = (
                db.query(Document, Claim, ParseJob)
                .join(Claim, Document.claim_id == Claim.id)
                .outerjoin(
                    ParseJob,
                    (ParseJob.claim_id == Claim.id)
                    & (
                        ParseJob.created_at
                        == db.query(func.max(ParseJob.created_at))
                        .filter(ParseJob.claim_id == Claim.id)
                        .correlate(Claim)
                        .scalar_subquery()
                    ),
                )
                .filter(Document.content_hash == single_hash)
                .first()
            )

            if row:
                existing_doc, existing_claim, parse_job = row
                logger.info(f"[Intake] Found existing claim {existing_claim.id} with same content hash")
                if existing_claim.status == "COMPLETED":
                    logger.info(f"[Intake] Claim {existing_claim.id} already completed; returning idempotently")
                    raise Ignore()
                if parse_job and parse_job.status in ("PENDING", "IN_PROGRESS", "QUEUED", "PARSING"):
                    logger.info(f"[Intake] Claim {existing_claim.id} already in progress")
                    raise Ignore()

        # --- STEP 2: Create claim ---
        claim = Claim(
            policy_id=policy_id,
            patient_id=patient_id,
            status="UPLOADED",
            source="PATIENT",
        )
        db.add(claim)
        db.flush()  # populate claim.id without committing
        claim_id = claim.id
        logger.info(f"[Intake] Created claim {claim_id}")

        # --- STEP 3: Deduplicate within this claim, relocate files, build Document objects ---
        from services.ingress.app.config import settings

        RAW_STORAGE = Path(settings.storage_root).resolve()

        # Bulk-fetch any intra-claim hash collisions in one query instead of one-per-file
        incoming_hashes = [m["content_hash"] for m in file_metadata]
        existing_hashes_in_claim: set[str] = {
            row[0]
            for row in db.query(Document.content_hash)
            .filter(Document.claim_id == claim_id, Document.content_hash.in_(incoming_hashes))
            .all()
        }

        added_hashes: list[str] = []  # track inserted docs for set_hash — avoids a re-query later

        for idx, metadata in enumerate(file_metadata):
            safe_name = metadata["safe_name"]
            content_hash = metadata["content_hash"]
            effective_ct = metadata["effective_ct"]
            temp_path = Path(metadata["path"])

            if content_hash in existing_hashes_in_claim:
                logger.info(f"[Intake] Skipping duplicate document in same claim: {safe_name}")
                temp_path.unlink(missing_ok=True)
                continue

            ext = Path(safe_name).suffix or ".bin"
            stored_name = f"{claim_id}_{idx}{ext}" if len(file_metadata) > 1 else f"{claim_id}{ext}"
            permanent_path = RAW_STORAGE / stored_name

            try:
                shutil.move(str(temp_path), str(permanent_path))
                logger.info(f"[Intake] Moved file: {temp_path} -> {permanent_path}")
            except OSError as e:
                logger.exception(f"[Intake] Failed to move file: {e}")
                temp_path.unlink(missing_ok=True)
                raise ValueError(f"Failed to relocate file {safe_name}: {e}")

            doc = Document(
                claim_id=claim_id,
                file_name=safe_name,
                file_type=effective_ct,
                minio_path=str(permanent_path),
                content_hash=content_hash,
            )
            db.add(doc)
            added_hashes.append(content_hash)
            existing_hashes_in_claim.add(content_hash)  # guard against dupes within this batch
            logger.info(f"[Intake] Created document {safe_name} for claim {claim_id} at {permanent_path}")

        # --- STEP 4: Compute set_hash from in-memory list — no re-query needed ---
        sorted_hashes = sorted(added_hashes)
        set_hash = hashlib.sha256(",".join(sorted_hashes).encode()).hexdigest()
        logger.info(f"[Intake] Calculated set_hash={set_hash} for claim {claim_id}")

        parse_job = ParseJob(claim_id=claim_id, status="PENDING", set_hash=set_hash)
        db.add(parse_job)

        db.commit()  # single commit for claim + documents + parse_job
        logger.info(f"[Intake] Committed claim {claim_id} with {len(added_hashes)} documents")

        _update_workflow_state(str(claim_id), "STARTING", status="RUNNING")

        return {"claim_id": str(claim_id)}

    except Ignore:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(f"[Intake] Task failed: {exc}")
        if _is_terminal_task_error(exc):
            raise Ignore() from exc
        if self.request.retries >= self.max_retries:
            error_msg = f"Intake task failed after {self.max_retries} retries: {exc}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        else:
            raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    dont_autoretry_for=(NonRetryableTaskError, Ignore),
    retry_backoff=True,
    max_retries=5,
    retry_jitter=True,
)
def finalize_claim_task(self, previous_result: Any) -> dict[str, Any]:
    """Finalize the claim after all pipeline stages are complete.
    
    Receives result from validator_task which contains claim_id.
    """
    claim_id = _claim_id_from_payload(previous_result)
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
                    "final_results": [previous_result],
                    "total_processing_seconds": total_processing_seconds,
                },
            )
        except Exception:
            pass

        return {
            "claim_id": claim_id,
            "status": "COMPLETED",
            "total_processing_seconds": total_processing_seconds,
            "results": [previous_result],
        }
    finally:
        db.close()


# ================================================================== inline pipeline (no Celery worker required)

def run_pipeline_inline(claim_id: str) -> dict[str, Any]:
    """Run the full claim pipeline synchronously in the current process.

    Used as a fallback when no Celery worker is available (e.g., dev mode where
    only the gateway is started) or when the operator explicitly opts into
    in-process execution via ``CLAIMGPT_INLINE_PIPELINE=1``.

    Each stage updates ``WorkflowState`` so the progress endpoint behaves the
    same as it would with a Celery worker. Failures in any stage mark the
    workflow ``FAILED`` and stop the chain — the same semantics as the Celery
    chain when a task raises.
    """
    import logging
    log = logging.getLogger("inline-pipeline")
    log.info(f"[InlinePipeline] starting for claim_id={claim_id}")

    cid = uuid.UUID(claim_id)

    # ---------- OCR ----------
    db = OcrSessionLocal()
    ocr_job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            log.warning(f"[InlinePipeline] Claim not found, aborting: {claim_id}")
            return {"claim_id": claim_id, "status": "NOT_FOUND"}
        job = OcrJob(claim_id=cid, status="QUEUED")
        db.add(job)
        db.commit()
        db.refresh(job)
        ocr_job_id = job.id
    finally:
        db.close()

    _update_workflow_state(claim_id, "OCR_IN_PROGRESS", status="RUNNING")
    try:
        outcome = _run_ocr_job(ocr_job_id)
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if status == "REJECTED":
            error_msg = str(outcome.get("reason") or "OCR rejected the document.")
            _mark_job_failed(ocr_job_id, error_msg, OcrSessionLocal)
            _update_workflow_state(claim_id, "OCR_REJECTED", status="FAILED")
            return {"claim_id": claim_id, "status": "OCR_REJECTED", "error": error_msg}
        if status == "FAILED":
            error_msg = str(outcome.get("reason") or "OCR failed.")
            _mark_job_failed(ocr_job_id, error_msg, OcrSessionLocal)
            _update_workflow_state(claim_id, "FAILED", status="FAILED")
            return {"claim_id": claim_id, "status": "FAILED", "error": error_msg}
    except Exception as exc:
        error_msg = f"OCR failed: {type(exc).__name__}: {exc}"
        log.exception(f"[InlinePipeline] OCR error for {claim_id}")
        _mark_job_failed(ocr_job_id, error_msg, OcrSessionLocal)
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        return {"claim_id": claim_id, "status": "FAILED", "error": error_msg}
    _update_workflow_state(claim_id, "OCR_COMPLETED", status="RUNNING")

    # ---------- Parser ----------
    db = ParserSessionLocal()
    parse_job_id = None
    try:
        job = ParseJob(claim_id=cid, status="QUEUED")
        db.add(job)
        db.commit()
        db.refresh(job)
        parse_job_id = job.id
    finally:
        db.close()

    _update_workflow_state(claim_id, "PARSING_IN_PROGRESS", status="RUNNING")
    try:
        _run_parse_job(parse_job_id)
    except Exception as exc:
        error_msg = f"Parser failed: {type(exc).__name__}: {exc}"
        log.exception(f"[InlinePipeline] Parser error for {claim_id}")
        _mark_job_failed(parse_job_id, error_msg, ParserSessionLocal)
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        return {"claim_id": claim_id, "status": "FAILED", "error": error_msg}
    _update_workflow_state(claim_id, "PARSING_COMPLETED", status="RUNNING")

    # ---------- Coding ----------
    _update_workflow_state(claim_id, "CODING_ANALYSIS", status="RUNNING")
    try:
        _run_coding_job(claim_id)
    except Exception as exc:
        log.exception(f"[InlinePipeline] Coding error for {claim_id}")
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        return {"claim_id": claim_id, "status": "FAILED", "error": f"Coding failed: {exc}"}
    _update_workflow_state(claim_id, "CODING_COMPLETED", status="RUNNING")

    # ---------- Risk ----------
    _update_workflow_state(claim_id, "RISK_ANALYSIS", status="RUNNING")
    try:
        _run_risk_job(claim_id)
    except Exception as exc:
        log.exception(f"[InlinePipeline] Risk error for {claim_id}")
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        return {"claim_id": claim_id, "status": "FAILED", "error": f"Risk failed: {exc}"}
    _update_workflow_state(claim_id, "RISK_COMPLETED", status="RUNNING")

    # ---------- Validator ----------
    _update_workflow_state(claim_id, "VALIDATION_RUNNING", status="RUNNING")
    validator_result: dict[str, Any] = {"claim_id": claim_id}
    try:
        validator_result = _run_validator_job(claim_id)
    except Exception as exc:
        log.exception(f"[InlinePipeline] Validator error for {claim_id}")
        _update_workflow_state(claim_id, "FAILED", status="FAILED")
        return {"claim_id": claim_id, "status": "FAILED", "error": f"Validator failed: {exc}"}
    _update_workflow_state(claim_id, "VALIDATION_COMPLETED", status="RUNNING")

    # ---------- Finalize ----------
    _update_workflow_state(claim_id, "FINALIZING", status="RUNNING")
    db = ValidatorSessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if claim:
            total_seconds = None
            if claim.created_at:
                total_seconds = max(0.0, (datetime.now(UTC) - claim.created_at).total_seconds())
            claim.status = "COMPLETED"
            db.commit()
            try:
                AuditLogger(db, "workflow").log(
                    "PIPELINE_COMPLETED",
                    claim_id=cid,
                    metadata={
                        "final_results": [validator_result],
                        "total_processing_seconds": total_seconds,
                        "executor": "inline",
                    },
                )
            except Exception:
                pass
    finally:
        db.close()
    _update_workflow_state(claim_id, "FINISHED", status="FINISHED")
    log.info(f"[InlinePipeline] completed claim_id={claim_id}")
    return {"claim_id": claim_id, "status": "COMPLETED", "results": [validator_result]}
