"""
Fraud detection engine — orchestrates rules + ML + LLM and blends
their scores into a single hybrid signal.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .config import settings
from .llm import assess_narrative
from .ml import build_ml_features, score_anomaly
from .models import Claim, FraudAssessment, MedicalCode, MedicalEntity, ParsedField
from .rules import FraudContext, RuleHit, aggregate_rules_score, run_rules

logger = logging.getLogger("fraud.engine")

MODEL_NAME = "claimgpt-fraud-hybrid"
MODEL_VERSION = "0.1.0"


@dataclass
class FraudResult:
    fraud_score: float
    fraud_category: str
    rules_score: float | None
    ml_score: float | None
    llm_score: float | None
    indicators: list[dict[str, Any]] = field(default_factory=list)


# ─────────────────────────────────────────────────────── context loaders
def _load_field_map(db: Session, cid: uuid.UUID) -> dict[str, Any]:
    rows = db.query(ParsedField).filter(ParsedField.claim_id == cid).all()
    return {r.field_name: r.field_value for r in rows}


def _load_codes(db: Session, cid: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.query(MedicalCode).filter(MedicalCode.claim_id == cid).all()
    return [
        {"code": r.code, "code_system": r.code_system, "is_primary": r.is_primary}
        for r in rows
    ]


def _load_entities(db: Session, cid: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.query(MedicalEntity).filter(MedicalEntity.claim_id == cid).all()
    return [{"entity_type": r.entity_type, "entity_text": r.entity_text} for r in rows]


def _load_history(db: Session, claim: Claim) -> list[dict[str, Any]]:
    """Recent claims for the same patient or policy, excluding this one."""
    if not (claim.patient_id or claim.policy_id):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.velocity_window_days * 3)
    q = db.query(Claim).filter(Claim.id != claim.id, Claim.created_at >= cutoff)
    filters = []
    if claim.patient_id:
        filters.append(Claim.patient_id == claim.patient_id)
    if claim.policy_id:
        filters.append(Claim.policy_id == claim.policy_id)
    q = q.filter(or_(*filters))
    return [{"claim_id": str(c.id), "created_at": c.created_at.isoformat() if c.created_at else None} for c in q.all()]


def _load_duplicate_candidates(
    db: Session, claim: Claim, history_ids: list[str]
) -> list[dict[str, Any]]:
    """For each prior claim, materialise the small fields used by duplicate rules."""
    if not history_ids:
        return []
    out: list[dict[str, Any]] = []
    uuid_ids = []
    for s in history_ids:
        try:
            uuid_ids.append(uuid.UUID(s))
        except ValueError:
            continue
    if not uuid_ids:
        return []

    # Pull amount + service date + provider + primary ICD for each prior claim
    pf_rows = (
        db.query(ParsedField)
        .filter(ParsedField.claim_id.in_(uuid_ids))
        .all()
    )
    by_claim: dict[uuid.UUID, dict[str, Any]] = {}
    for r in pf_rows:
        b = by_claim.setdefault(r.claim_id, {})
        b[r.field_name] = r.field_value

    code_rows = (
        db.query(MedicalCode)
        .filter(and_(MedicalCode.claim_id.in_(uuid_ids), MedicalCode.code_system == "ICD10", MedicalCode.is_primary.is_(True)))
        .all()
    )
    primary_by_claim = {r.claim_id: r.code for r in code_rows}

    for cid, fields in by_claim.items():
        amount_raw = (
            fields.get("total_amount") or fields.get("grand_total")
            or fields.get("net_amount") or fields.get("amount")
        )
        try:
            amount = float(str(amount_raw).replace(",", "").strip()) if amount_raw else None
        except ValueError:
            amount = None
        service_date = (
            fields.get("service_date") or fields.get("admission_date")
            or fields.get("date_of_service")
        )
        out.append({
            "claim_id": str(cid),
            "total_amount": amount,
            "service_date": service_date,
            "provider": (fields.get("provider_name") or fields.get("hospital_name") or "").strip().lower(),
            "primary_icd": primary_by_claim.get(cid),
        })
    return out


# ─────────────────────────────────────────────────────── main entry
def assess_claim(db: Session, claim: Claim) -> FraudResult:
    """Run all enabled detector layers and return a blended assessment."""
    cid = claim.id
    field_map = _load_field_map(db, cid)
    codes = _load_codes(db, cid)
    entities = _load_entities(db, cid)
    history = _load_history(db, claim)
    duplicates = _load_duplicate_candidates(db, claim, [h["claim_id"] for h in history])

    # Latest predictor signal feeds two things: ML feature + a soft rule
    rejection_score = None
    if claim.predictions:
        latest = max(claim.predictions, key=lambda p: p.created_at or datetime.min.replace(tzinfo=timezone.utc))
        rejection_score = latest.rejection_score

    ctx = FraudContext(
        claim_id=str(cid),
        field_map=field_map,
        codes=codes,
        entities=entities,
        rejection_score=rejection_score,
        history=history,
        duplicate_candidates=duplicates,
        velocity_window_days=settings.velocity_window_days,
        velocity_max_claims=settings.velocity_max_claims,
        provider_blacklist=set(),  # plug a real source here later
    )

    indicators: list[dict[str, Any]] = []

    # ── Rules layer ─────────────────────────────────────
    rules_score: float | None = None
    if settings.rules_enabled:
        hits: list[RuleHit] = run_rules(ctx)
        rules_score = aggregate_rules_score(hits)
        for h in hits:
            indicators.append({
                "code": h.code,
                "name": h.name,
                "layer": "rules",
                "severity": h.severity,
                "weight": h.weight,
                "message": h.message,
                "evidence": h.evidence,
            })

    # ── ML layer ────────────────────────────────────────
    ml_score: float | None = None
    ml_model_name = None
    if settings.ml_enabled:
        feats = build_ml_features(field_map, codes, history_count_30d=len(history))
        ml_score, ml_model_name = score_anomaly(feats)
        if ml_score >= 0.6:
            indicators.append({
                "code": "M-ANOM-01",
                "name": "ML anomaly detector",
                "layer": "ml",
                "severity": "HIGH" if ml_score >= 0.8 else "WARN",
                "weight": ml_score,
                "message": f"Anomaly score {ml_score:.2f} ({ml_model_name})",
                "evidence": {"top_features": _top_feature_signals(feats)},
            })

    # ── LLM layer ───────────────────────────────────────
    llm_score: float | None = None
    if settings.llm_enabled:
        try:
            llm_score, llm_indicators = assess_narrative(field_map, codes)
            indicators.extend(llm_indicators)
        except Exception:
            logger.exception("LLM layer failed")
            llm_score = None

    # ── Blend ───────────────────────────────────────────
    fraud_score = _blend(rules_score, ml_score, llm_score)
    category = _category(fraud_score)

    return FraudResult(
        fraud_score=fraud_score,
        fraud_category=category,
        rules_score=rules_score,
        ml_score=ml_score,
        llm_score=llm_score,
        indicators=indicators,
    )


def _blend(rules: float | None, ml: float | None, llm: float | None) -> float:
    """Weighted average of available components, renormalised when
    some layers are disabled / unavailable."""
    pairs: list[tuple[float, float]] = []
    if rules is not None:
        pairs.append((settings.weight_rules, rules))
    if ml is not None:
        pairs.append((settings.weight_ml, ml))
    if llm is not None:
        pairs.append((settings.weight_llm, llm))
    if not pairs:
        return 0.0
    total_w = sum(w for w, _ in pairs)
    if total_w <= 0:
        return 0.0
    blended = sum(w * s for w, s in pairs) / total_w
    return round(max(0.0, min(1.0, blended)), 4)


def _category(score: float) -> str:
    if score >= settings.threshold_high:
        return "HIGH"
    if score >= settings.threshold_medium:
        return "MEDIUM"
    return "LOW"


def _top_feature_signals(features: dict[str, float]) -> dict[str, float]:
    """Trim to the most informative features for the indicator evidence."""
    interesting = ("claim_to_insured", "icu_ratio", "amount_per_day", "history_count_30d")
    return {k: round(features.get(k, 0.0), 4) for k in interesting}


# ─────────────────────────────────────────────────────── persistence
def persist(db: Session, claim_id: uuid.UUID, result: FraudResult) -> FraudAssessment:
    row = FraudAssessment(
        claim_id=claim_id,
        fraud_score=result.fraud_score,
        fraud_category=result.fraud_category,
        rules_score=result.rules_score,
        ml_score=result.ml_score,
        llm_score=result.llm_score,
        indicators=result.indicators,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
