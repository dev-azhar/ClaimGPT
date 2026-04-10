from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import Claim, MedicalCode, ParsedField, Prediction, Validation
from .rules import run_rules
from .schemas import ValidationOut, ValidationResultOut

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("validator")

app = FastAPI(title="ClaimGPT Validator Service")

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
    init_tracing("validator")
    init_metrics("validator")
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


# ------------------------------------------------------------------ helpers

def _build_context(db: Session, cid: uuid.UUID) -> dict[str, Any]:
    """Assemble validation context from upstream data."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == cid).all()
    field_map = {r.field_name: r.field_value for r in pf_rows}

    codes = [
        {"code": c.code, "code_system": c.code_system, "is_primary": c.is_primary}
        for c in db.query(MedicalCode).filter(MedicalCode.claim_id == cid).all()
    ]

    pred = (
        db.query(Prediction)
        .filter(Prediction.claim_id == cid)
        .order_by(Prediction.created_at.desc())
        .first()
    )

    return {
        "field_map": field_map,
        "codes": codes,
        "rejection_score": pred.rejection_score if pred else None,
    }


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


@router.post("/validate/{claim_id}", response_model=ValidationResultOut)
def run_validation(claim_id: str, db: Session = Depends(get_db)):
    """
    Run all validation rules against a claim. Idempotent — replaces
    previous validation results.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    ctx = _build_context(db, cid)
    results = run_rules(ctx)

    # Wipe old validations
    db.query(Validation).filter(Validation.claim_id == cid).delete()

    for r in results:
        db.add(Validation(
            claim_id=cid,
            rule_id=r.rule_id,
            rule_name=r.rule_name,
            severity=r.severity,
            message=r.message,
            passed=r.passed,
        ))

    errors = sum(1 for r in results if not r.passed and r.severity == "ERROR")
    claim.status = "VALIDATED" if errors == 0 else "VALIDATION_FAILED"
    db.commit()

    logger.info("Validation for claim %s: %d rules, %d errors", cid, len(results), errors)

    return _build_response(cid, claim.status, results)


@router.get("/validate/{claim_id}", response_model=ValidationResultOut)
def get_validation(claim_id: str, db: Session = Depends(get_db)):
    """Retrieve validation results for a claim."""
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    rows = db.query(Validation).filter(Validation.claim_id == cid).all()
    return ValidationResultOut(
        claim_id=cid,
        status=claim.status,
        total_rules=len(rows),
        passed=sum(1 for r in rows if r.passed),
        failed=sum(1 for r in rows if not r.passed),
        warnings=sum(1 for r in rows if r.severity == "WARN" and not r.passed),
        results=[
            ValidationOut(
                id=r.id,
                rule_id=r.rule_id,
                rule_name=r.rule_name,
                severity=r.severity,
                message=r.message,
                passed=r.passed,
                evaluated_at=r.evaluated_at,
            )
            for r in rows
        ],
    )


def _build_response(cid, status, results):
    return ValidationResultOut(
        claim_id=cid,
        status=status,
        total_rules=len(results),
        passed=sum(1 for r in results if r.passed),
        failed=sum(1 for r in results if not r.passed),
        warnings=sum(1 for r in results if r.severity == "WARN" and not r.passed),
        results=[
            ValidationOut(
                id=uuid.uuid4(),  # placeholder — real IDs come from DB
                rule_id=r.rule_id,
                rule_name=r.rule_name,
                severity=r.severity,
                message=r.message,
                passed=r.passed,
                evaluated_at=None,
            )
            for r in results
        ],
    )


# ── Include router (standalone mode) ──
app.include_router(router)
