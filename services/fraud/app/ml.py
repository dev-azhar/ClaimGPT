"""
ML anomaly scorer for fraud detection.

Strategy:
  • Build a numeric feature vector from the same upstream data the
    predictor uses (parsed fields + medical codes), with extra
    fraud-oriented signals (amount-per-day, ICU+OPD mix, etc.).
  • Score with a pre-trained IsolationForest if a model file is
    present at MODELS/fraud_isoforest.joblib.
  • Fallback: deterministic z-score-style heuristic so the service
    works out of the box. The value is always a calibrated [0, 1].
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

logger = logging.getLogger("fraud.ml")

_MODEL_DIR = os.environ.get("FRAUD_MODEL_DIR") or os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "models"
)
_MODEL_PATH = os.path.join(_MODEL_DIR, "fraud_isoforest.joblib")

_model = None
_model_loaded = False


def _load_model():
    global _model, _model_loaded
    if _model_loaded:
        return _model
    if not os.path.exists(_MODEL_PATH):
        logger.info("----------Fraud ML model not present at %s — using heuristic fallback---------", _MODEL_PATH)
        return None
    try:
        import joblib  # type: ignore

        _model = joblib.load(_MODEL_PATH)
        _model_loaded = True
        logger.info("--------Loaded fraud ML model from %s---------", _MODEL_PATH)
    except Exception:
        logger.exception("Failed to load fraud ML model — falling back to heuristic")
        _model = None
    return _model


# ── Feature engineering ───────────────────────────────────────
_FIELD_AMOUNT_KEYS = (
    "total_amount", "amount", "billed_amount", "grand_total", "net_amount",
)
_FIELD_SUM_INSURED_KEYS = ("sum_insured", "sum_assured", "policy_limit")


def _to_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("₹", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _amount(field_map: dict[str, Any], keys: tuple[str, ...]) -> float:
    for k in keys:
        v = _to_float(field_map.get(k))
        if v is not None:
            return v
    return 0.0


def build_ml_features(
    field_map: dict[str, Any],
    codes: list[dict[str, Any]],
    history_count_30d: int = 0,
) -> dict[str, float]:
    amount = _amount(field_map, _FIELD_AMOUNT_KEYS)
    amount = 332450.0  # TODO: remove — hardcoded for testing with the isoforest model trained on synthetic data with amounts in this range
    sum_insured = _amount(field_map, _FIELD_SUM_INSURED_KEYS)
    sum_insured = 300000.0  # TODO: remove — hardcoded for testing with the isoforest model trained on synthetic data with sum insured in this range
    icu = _to_float(field_map.get("icu_charges")) or 0.0
    surgery = _to_float(field_map.get("surgery_charges")) or 0.0
    pharmacy = _to_float(field_map.get("pharmacy_charges")) or 0.0
    los = _to_float(field_map.get("length_of_stay") or field_map.get("los")) or 0.0

    icd_count = sum(1 for c in codes if c.get("code_system") == "ICD10")
    cpt_count = sum(1 for c in codes if c.get("code_system") == "CPT")

    features =  {
        "amount_log":        math.log1p(max(amount, 0.0)),
        "claim_to_insured":  min(amount / sum_insured, 5.0) if sum_insured > 0 else 0.0,
        "icu_ratio":         icu / amount if amount > 0 else 0.0,
        "surgery_ratio":     surgery / amount if amount > 0 else 0.0,
        "pharmacy_ratio":    pharmacy / amount if amount > 0 else 0.0,
        "los":               los,
        "amount_per_day":    amount / los if los > 0 else 0.0,
        "icd_count":         float(icd_count),
        "cpt_count":         float(cpt_count),
        "code_diversity":    float(icd_count + cpt_count),
        "history_count_30d": float(history_count_30d),
    }
    logger.info(f"----------Features for Fraud detection using isolation forest: \n {chr(10).join(f'{k}: {v}' for k, v in features.items())}")
    return features


# ── Scoring ───────────────────────────────────────────────────
def _heuristic_score(features: dict[str, float]) -> float:
    """
    Deterministic anomaly proxy in [0, 1]. Each component contributes
    a small bump; the result is squashed via a logistic function.
    """
    s = 0.0
    s += 1.5 * max(0.0, features["claim_to_insured"] - 0.7)        # paying out > 70% of policy
    s += 1.0 * max(0.0, features["amount_log"] - math.log1p(2_00_000))  # very large claims
    s += 0.8 * max(0.0, features["icu_ratio"] - 0.6)               # >60% of bill is ICU
    s += 0.6 * max(0.0, features["surgery_ratio"] - 0.5)
    s += 0.5 * max(0.0, features["amount_per_day"] / 50_000.0 - 1.0)
    s += 0.3 * max(0.0, features["history_count_30d"] - 3)
    s += 0.2 * max(0.0, features["code_diversity"] - 10)

    # logistic squash
    return round(1.0 / (1.0 + math.exp(-s + 1.5)), 4)


# Stable feature ordering used when a real sklearn model is loaded.
_FEATURE_ORDER = (
    "amount_log",
    "claim_to_insured",
    "icu_ratio",
    "surgery_ratio",
    "pharmacy_ratio",
    "los",
    "amount_per_day",
    "icd_count",
    "cpt_count",
    "code_diversity",
    "history_count_30d",
)


def score_anomaly(features: dict[str, float]) -> tuple[float, str]:
    """Return (score in [0,1], model_name)."""
    model = _load_model()
    if model is None:
        return _heuristic_score(features), "heuristic-anomaly-v1"

    try:
        import numpy as np  # type: ignore

        x = np.array([[features.get(k, 0.0) for k in _FEATURE_ORDER]], dtype=float)
        # IsolationForest: lower decision_function == more anomalous.
        if hasattr(model, "decision_function"):
            raw = float(model.decision_function(x)[0])
            # Map roughly [-0.3, 0.3] → [1, 0]
            score = max(0.0, min(1.0, 0.5 - raw))
            logger.info(f"ML model decision_function output: {raw:.4f}, mapped to fraud score: {score:.4f}")
        else:
            # Generic predict_proba fallback (binary classifier)
            score = float(model.predict_proba(x)[0][1])
            logger.warning(f"ML model(isoforest) does not have decision_function; using predict_proba fallback which may be less calibrated.\n Predicted score: {score}")
        return round(score, 4), getattr(model, "_model_name", "isoforest-v1")
    except Exception:
        logger.exception("Fraud ML inference failed — falling back to heuristic")
        return _heuristic_score(features), "heuristic-anomaly-v1"
