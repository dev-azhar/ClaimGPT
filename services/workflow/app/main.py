from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import Claim, WorkflowJob
from .pipeline import run_pipeline
from .schemas import WorkflowJobOut

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("workflow")

app = FastAPI(title="ClaimGPT Workflow Orchestrator")

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
    init_tracing("workflow")
    init_metrics("workflow")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


@app.on_event("shutdown")
def _shutdown():
    engine.dispose()


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

def _execute_workflow(job_id: uuid.UUID) -> None:
    """Background worker that runs the full pipeline."""
    db = SessionLocal()
    try:
        job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
        if not job:
            logger.error("WorkflowJob %s not found", job_id)
            return

        job.status = "RUNNING"
        job.started_at = datetime.now(datetime.UTC)
        db.commit()

        claim = db.query(Claim).filter(Claim.id == job.claim_id).first()
        if claim:
            claim.status = "PROCESSING"
            db.commit()

        result = run_pipeline(str(job.claim_id))

        if result.success:
            job.status = "COMPLETED"
            job.current_step = "done"
            if claim:
                claim.status = "COMPLETED"
        else:
            job.status = "FAILED"
            job.current_step = result.failed_step
            job.error_message = result.error
            if claim:
                claim.status = "WORKFLOW_FAILED"

        job.completed_at = datetime.now(datetime.UTC)
        db.commit()

        logger.info("Workflow job %s finished — status=%s", job_id, job.status)

    except Exception:
        db.rollback()
        logger.exception("Workflow job %s crashed", job_id)
        try:
            job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
            if job:
                job.status = "FAILED"
                job.error_message = "Internal error"
                job.completed_at = datetime.now(datetime.UTC)
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
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


@router.post("/start/{claim_id}", response_model=WorkflowJobOut, status_code=202)
def start_workflow(
    claim_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Kick off the end-to-end pipeline for a claim:
    OCR → Parse → Code-Suggest → Predict → Validate
    Returns a job_id for polling.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    job = WorkflowJob(
        claim_id=cid,
        job_type="FULL_PIPELINE",
        status="QUEUED",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_execute_workflow, job.id)

    return WorkflowJobOut(
        job_id=job.id,
        claim_id=job.claim_id,
        job_type=job.job_type,
        status=job.status,
        started_at=job.started_at,
    )


@router.get("/{job_id}", response_model=WorkflowJobOut)
def get_workflow_status(job_id: str, db: Session = Depends(get_db)):
    """Poll workflow job status."""
    jid = _parse_uuid(job_id)

    job = db.query(WorkflowJob).filter(WorkflowJob.id == jid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Workflow job not found")

    return WorkflowJobOut(
        job_id=job.id,
        claim_id=job.claim_id,
        job_type=job.job_type,
        status=job.status,
        current_step=job.current_step,
        retries=job.retries,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


# ── Include router (standalone mode) ──
app.include_router(router)
