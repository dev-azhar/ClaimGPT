from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .engine import MODEL_NAME, MODEL_VERSION, assess_claim, persist
from .models import Claim, FraudAssessment
from .schemas import FraudAssessmentOut, FraudIndicator, FraudResultOut

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("fraud")

app = FastAPI(title="ClaimGPT Fraud Detection Service")

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
    init_tracing("fraud")
    init_metrics("fraud")
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


# ------------------------------------------------------------------ routes
router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "layers": {
            "rules": settings.rules_enabled,
            "ml": settings.ml_enabled,
            "llm": settings.llm_enabled,
        },
    }


@router.post("/detect/{claim_id}", response_model=FraudResultOut)
def run_detection(claim_id: str, db: Session = Depends(get_db)):
    """Run all enabled fraud detector layers and persist the assessment."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    result = assess_claim(db, claim)
    row = persist(db, cid, result)

    logger.info(
        "Fraud assessment for claim %s: score=%.4f (%s) — rules=%s ml=%s llm=%s",
        cid, result.fraud_score, result.fraud_category,
        result.rules_score, result.ml_score, result.llm_score,
    )

    return _to_response(claim.status, row)


@router.get("/detect/{claim_id}", response_model=FraudResultOut)
def get_assessment(claim_id: str, db: Session = Depends(get_db)):
    """Return the latest fraud assessment for a claim."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    row = (
        db.query(FraudAssessment)
        .filter(FraudAssessment.claim_id == cid)
        .order_by(FraudAssessment.created_at.desc())
        .first()
    )
    return _to_response(claim.status, row, claim_id=cid)


def _to_response(status: str, row: FraudAssessment | None, claim_id: uuid.UUID | None = None) -> FraudResultOut:
    if row is None:
        return FraudResultOut(claim_id=claim_id, status=status, assessment=None)
    indicators = [
        FraudIndicator(**ind) for ind in (row.indicators or [])
    ]
    return FraudResultOut(
        claim_id=row.claim_id,
        status=status,
        assessment=FraudAssessmentOut(
            id=row.id,
            claim_id=row.claim_id,
            fraud_score=row.fraud_score,
            fraud_category=row.fraud_category,
            rules_score=row.rules_score,
            ml_score=row.ml_score,
            llm_score=row.llm_score,
            indicators=indicators,
            model_name=row.model_name,
            model_version=row.model_version,
            created_at=row.created_at,
        ),
    )


# Mount the router on the standalone app too — when running this service
# directly via uvicorn, otherwise only the gateway sees the routes.
app.include_router(router)

