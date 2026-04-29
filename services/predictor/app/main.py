from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .engine import build_features, predict, _score_to_category
from .models import (
    Claim,
    Feature,
    MedicalCode,
    MedicalEntity,
    ParsedField,
    Prediction,
)
from .schemas import FeatureOut, PredictionOut, PredictResultOut

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("predictor")

app = FastAPI(title="ClaimGPT Predictor Service")

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
    init_tracing("predictor")
    init_metrics("predictor")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


@app.on_event("startup")
def _startup():
    """Pre-load ML models so the first prediction request is fast."""
    from .engine import _load_models
    logger.info("Pre-loading prediction models …")
    _load_models()
    logger.info("Model pre-loading complete")


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
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


@router.post("/predict/{claim_id}", response_model=PredictResultOut)
def run_prediction(claim_id: str, db: Session = Depends(get_db)):
    """
    Build feature vector from parsed fields + medical codes, run the
    rejection-risk scorer, persist results, and return them.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Gather upstream data
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == cid).all()
    ent_rows = db.query(MedicalEntity).filter(MedicalEntity.claim_id == cid).all()
    code_rows = db.query(MedicalCode).filter(MedicalCode.claim_id == cid).all()

    parsed = [{"field_name": r.field_name, "field_value": r.field_value} for r in pf_rows]
    entities = [{"entity_type": r.entity_type, "entity_text": r.entity_text} for r in ent_rows]
    codes = [
        {"code": r.code, "code_system": r.code_system, "is_primary": r.is_primary}
        for r in code_rows
    ]

    features = build_features(parsed, entities, codes)
    result = predict(features)

    # Persist feature vector (upsert)
    feat = db.query(Feature).filter(Feature.claim_id == cid).first()
    if feat:
        feat.feature_vector = result.feature_vector
    else:
        db.add(Feature(claim_id=cid, feature_vector=result.feature_vector))

    # Persist prediction
    pred = Prediction(
        claim_id=cid,
        rejection_score=result.rejection_score,
        top_reasons=result.top_reasons,
        model_name=result.model_name,
        model_version=result.model_version,
    )
    db.add(pred)

    db.commit()
    db.refresh(pred)

    logger.info("Prediction for claim %s: score=%.4f (%s)", cid, result.rejection_score, result.risk_category)

    return _build_response(db, cid, claim.status, pred)


@router.get("/predict/{claim_id}", response_model=PredictResultOut)
def get_prediction(claim_id: str, db: Session = Depends(get_db)):
    """Retrieve the latest prediction for a claim."""
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    pred = (
        db.query(Prediction)
        .filter(Prediction.claim_id == cid)
        .order_by(Prediction.created_at.desc())
        .first()
    )

    return _build_response(db, cid, claim.status, pred)


def _build_response(db, cid, status, pred):
    feat = db.query(Feature).filter(Feature.claim_id == cid).first()
    return PredictResultOut(
        claim_id=cid,
        status=status,
        prediction=PredictionOut(
            id=pred.id,
            claim_id=pred.claim_id,
            rejection_score=pred.rejection_score,
            risk_category=_score_to_category(pred.rejection_score) if pred.rejection_score is not None else None,
            top_reasons=pred.top_reasons,
            model_name=pred.model_name,
            model_version=pred.model_version,
            created_at=pred.created_at,
        ) if pred else None,
        features=FeatureOut(
            claim_id=feat.claim_id,
            feature_vector=feat.feature_vector,
            generated_at=feat.generated_at,
        ) if feat else None,
    )


# ------------------------------------------------------------------ Feature Store endpoints

@router.get("/features/{claim_id}", response_model=FeatureOut)
def get_features(claim_id: str, db: Session = Depends(get_db)):
    """
    Feature Store: retrieve the feature vector for a claim.
    If features haven't been computed yet, build them on the fly and cache.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    feat = db.query(Feature).filter(Feature.claim_id == cid).first()

    if not feat:
        # Build features on demand
        pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == cid).all()
        ent_rows = db.query(MedicalEntity).filter(MedicalEntity.claim_id == cid).all()
        code_rows = db.query(MedicalCode).filter(MedicalCode.claim_id == cid).all()

        parsed = [{"field_name": r.field_name, "field_value": r.field_value} for r in pf_rows]
        entities = [{"entity_type": r.entity_type, "entity_text": r.entity_text} for r in ent_rows]
        codes = [
            {"code": r.code, "code_system": r.code_system, "is_primary": r.is_primary}
            for r in code_rows
        ]

        feature_vec = build_features(parsed, entities, codes)
        feat = Feature(claim_id=cid, feature_vector=feature_vec)
        db.add(feat)
        db.commit()
        db.refresh(feat)

    return FeatureOut(
        claim_id=feat.claim_id,
        feature_vector=feat.feature_vector,
        generated_at=feat.generated_at,
    )


# ── Include router (standalone mode) ──
app.include_router(router)
