#!/usr/bin/env python3
import os
import sys
import uuid
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Setup basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reprocess-script")

from services.shared_tasks import (
    _run_coding_job,
    _run_risk_job,
    _run_validator_job,
    _update_workflow_state,
)
from services.parser.app.main import _run_parse_job
from libs.shared.models import Claim, ParseJob
from libs.utils.audit import AuditLogger
from services.parser.app.db import SessionLocal as ParserSessionLocal
from services.validator.app.db import SessionLocal as ValidatorSessionLocal

UTC = timezone.utc

def reprocess_claim(claim_uuid_str: str):
    logger.info(f"=== STARTING REPROCESSING FOR CLAIM: {claim_uuid_str} ===")
    cid = uuid.UUID(claim_uuid_str)
    
    # 1. Start Parser Job
    logger.info("--> [1/5] Starting Parser Job...")
    db = ParserSessionLocal()
    parse_job_id = None
    try:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            logger.error(f"Claim {claim_uuid_str} not found in database!")
            return
        
        job = ParseJob(claim_id=cid, status="QUEUED")
        db.add(job)
        db.commit()
        db.refresh(job)
        parse_job_id = job.id
    finally:
        db.close()
        
    _update_workflow_state(claim_uuid_str, "PARSING_IN_PROGRESS", status="RUNNING")
    try:
        _run_parse_job(parse_job_id)
        logger.info(f"Parser Job {parse_job_id} completed successfully.")
    except Exception as exc:
        logger.exception(f"Parser failed for claim {claim_uuid_str}")
        _update_workflow_state(claim_uuid_str, "FAILED", status="FAILED")
        return
    _update_workflow_state(claim_uuid_str, "PARSING_COMPLETED", status="RUNNING")
    
    # 2. Run Coding Job
    logger.info("--> [2/5] Starting Coding Job...")
    _update_workflow_state(claim_uuid_str, "CODING_ANALYSIS", status="RUNNING")
    try:
        _run_coding_job(claim_uuid_str)
        logger.info("Coding Job completed successfully.")
    except Exception as exc:
        logger.exception(f"Coding failed for claim {claim_uuid_str}")
        _update_workflow_state(claim_uuid_str, "FAILED", status="FAILED")
        return
    _update_workflow_state(claim_uuid_str, "CODING_COMPLETED", status="RUNNING")
    
    # 3. Run Risk Job
    logger.info("--> [3/5] Starting Risk Job...")
    _update_workflow_state(claim_uuid_str, "RISK_ANALYSIS", status="RUNNING")
    try:
        _run_risk_job(claim_uuid_str)
        logger.info("Risk Job completed successfully.")
    except Exception as exc:
        logger.exception(f"Risk failed for claim {claim_uuid_str}")
        _update_workflow_state(claim_uuid_str, "FAILED", status="FAILED")
        return
    _update_workflow_state(claim_uuid_str, "RISK_COMPLETED", status="RUNNING")
    
    # 4. Run Validator Job
    logger.info("--> [4/5] Starting Validator Job...")
    _update_workflow_state(claim_uuid_str, "VALIDATION_RUNNING", status="RUNNING")
    validator_result = {}
    try:
        validator_result = _run_validator_job(claim_uuid_str)
        logger.info("Validator Job completed successfully.")
    except Exception as exc:
        logger.exception(f"Validator failed for claim {claim_uuid_str}")
        _update_workflow_state(claim_uuid_str, "FAILED", status="FAILED")
        return
    _update_workflow_state(claim_uuid_str, "VALIDATION_COMPLETED", status="RUNNING")
    
    # 5. Finalize Claim
    logger.info("--> [5/5] Finalizing Claim...")
    _update_workflow_state(claim_uuid_str, "FINALIZING", status="RUNNING")
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
                        "executor": "reprocess_script",
                    },
                )
            except Exception:
                pass
    finally:
        db.close()
    _update_workflow_state(claim_uuid_str, "FINISHED", status="FINISHED")
    logger.info(f"=== COMPLETED REPROCESSING FOR CLAIM: {claim_uuid_str} ===\n")

if __name__ == "__main__":
    claims_to_reprocess = [
        "253699a0-81f1-4011-9c1a-132e03c4cdf4", # Amreen Azhar Shaikh
        "ea78dafc-fd72-4068-b189-a20de318f537", # Usha Chouhan
        "66ad6449-a8ba-4265-bb25-61819cbcab3e"  # Saraswati Bai
    ]
    
    for claim_id in claims_to_reprocess:
        reprocess_claim(claim_id)
        
    logger.info("ALL CLAIMS REPROCESSED SUCCESSFULLY!")
