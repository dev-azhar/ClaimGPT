"""
Feature engineering + scoring engine for claim rejection prediction.

Strategy (ordered by priority):
  1. **XGBoost** — gradient-boosted tree classifier trained on historical claim
     features.  A pre-trained model is loaded from disk; if none exists the
     engine auto-trains on a synthetic dataset so the pipeline always works
     out-of-the-box.
  2. **LightGBM** — used as an ensemble secondary scorer if available.
  3. **Heuristic fallback** — rule-based scorer when neither library is installed.

The feature vector is built from parsed fields, NER entities, and medical codes
produced by upstream services.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import settings

logger = logging.getLogger("predictor.engine")

# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class PredictionResult:
    rejection_score: float
    top_reasons: list[dict[str, Any]]
    feature_vector: dict[str, Any]
    model_name: str = settings.model_name
    model_version: str = settings.model_version


# ------------------------------------------------------------------
# Feature engineering (shared by all backends)
# ------------------------------------------------------------------

# Canonical feature order — MUST match training order
FEATURE_NAMES = [
    "has_patient_name",
    "has_policy_number",
    "has_diagnosis",
    "has_service_date",
    "has_total_amount",
    "has_provider",
    "num_parsed_fields",
    "num_entities",
    "num_icd_codes",
    "num_cpt_codes",
    "has_primary_icd",
    "num_diagnosis_types",
    "total_amount_log",
    "amount_per_cpt_log",
]


def build_features(
    parsed_fields: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    codes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a feature vector from upstream pipeline data."""
    field_map = {f["field_name"]: f.get("field_value") for f in parsed_fields}

    raw_amount = field_map.get("total_amount")
    try:
        amount_val = float(str(raw_amount).replace(",", "")) if raw_amount else 0.0
    except (ValueError, TypeError):
        amount_val = 0.0

    return {
        "has_patient_name": int(bool(field_map.get("patient_name"))),
        "has_policy_number": int(bool(field_map.get("policy_number"))),
        "has_diagnosis": int(bool(field_map.get("diagnosis"))),
        "has_service_date": int(bool(field_map.get("service_date"))),
        "has_total_amount": int(bool(field_map.get("total_amount"))),
        "has_provider": int(bool(field_map.get("provider_name"))),
        "num_parsed_fields": len(parsed_fields),
        "num_entities": len(entities),
        "num_icd_codes": sum(1 for c in codes if c.get("code_system") == "ICD10"),
        "num_cpt_codes": sum(1 for c in codes if c.get("code_system") == "CPT"),
        "has_primary_icd": int(any(
            c.get("is_primary") and c.get("code_system") == "ICD10" for c in codes
        )),
        "num_diagnosis_types": len({
            e["entity_type"] for e in entities if e.get("entity_type") == "DIAGNOSIS"
        }),
        "total_amount_log": float(np.log1p(amount_val)),
        "amount_per_cpt_log": float(np.log1p(amount_val / max(1, sum(1 for c in codes if c.get("code_system") == "CPT")))),
    }


def _features_to_array(features: dict[str, Any]) -> np.ndarray:
    """Convert feature dict → 1-D numpy array in canonical order."""
    return np.array([float(features.get(f, 0)) for f in FEATURE_NAMES], dtype=np.float32)


# ------------------------------------------------------------------
# XGBoost model management
# ------------------------------------------------------------------
_MODEL_DIR = Path(os.getenv("PREDICTOR_MODEL_DIR", "models"))
_XGB_PATH = _MODEL_DIR / "xgb_rejection.json"
_LGBM_PATH = _MODEL_DIR / "lgbm_rejection.txt"

_xgb_model = None
_lgbm_model = None
_models_load_attempted = False


def _validate_lightgbm_model_file(model_path: Path, num_features: int) -> bool:
    """
    Validate a LightGBM model in a subprocess.

    Some malformed model files can trigger native LightGBM fatals that abort
    the interpreter process; subprocess isolation keeps the service alive.
    """
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "import numpy as np\n"
        "import lightgbm as lgb\n"
        "p=Path(sys.argv[1])\n"
        "n=int(sys.argv[2])\n"
        "b=lgb.Booster(model_file=str(p))\n"
        "_ = b.predict(np.zeros((1,n),dtype=float))\n"
        "print('OK')\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(model_path), str(num_features)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode == 0:
            return True
        logger.warning(
            "LightGBM model validation failed (code=%s): %s",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:500],
        )
        return False
    except Exception:
        logger.warning("LightGBM model validation probe failed", exc_info=True)
        return False


def _generate_synthetic_data(n_samples: int = 2000, seed: int = 42):
    """
    Generate synthetic claim feature vectors + labels for initial training.

    The synthetic labels encode realistic rejection logic:
      - Missing critical fields → high rejection prob
      - No ICD/CPT codes → moderate rejection prob
      - Low amount + complete fields → low rejection prob
    """
    rng = np.random.RandomState(seed)
    X = np.zeros((n_samples, len(FEATURE_NAMES)), dtype=np.float32)
    y = np.zeros(n_samples, dtype=np.int32)

    for i in range(n_samples):
        has_name = rng.choice([0, 1], p=[0.05, 0.95])
        has_policy = rng.choice([0, 1], p=[0.08, 0.92])
        has_diag = rng.choice([0, 1], p=[0.10, 0.90])
        has_date = rng.choice([0, 1], p=[0.07, 0.93])
        has_amount = rng.choice([0, 1], p=[0.12, 0.88])
        has_provider = rng.choice([0, 1], p=[0.10, 0.90])
        n_fields = rng.randint(0, 16)
        n_ents = rng.randint(0, 12)
        n_icd = rng.randint(0, 6)
        n_cpt = rng.randint(0, 4)
        has_pri = int(n_icd > 0 and rng.random() > 0.2)
        n_diag_types = min(n_ents, rng.randint(0, 4))
        amount = rng.lognormal(7, 2)  # realistic medical amounts
        amount_per_cpt = amount / max(1, n_cpt)

        X[i] = [
            has_name, has_policy, has_diag, has_date, has_amount,
            has_provider, n_fields, n_ents, n_icd, n_cpt,
            has_pri, n_diag_types, float(np.log1p(amount)), float(np.log1p(amount_per_cpt)),
        ]

        # Rejection probability based on realistic rules
        reject_prob = 0.05  # baseline
        missing = sum(1 for v in [has_name, has_policy, has_diag, has_date, has_amount] if v == 0)
        reject_prob += missing * 0.15
        if n_icd == 0:
            reject_prob += 0.12
        if n_cpt == 0:
            reject_prob += 0.08
        if not has_pri:
            reject_prob += 0.06
        if n_fields < 3:
            reject_prob += 0.10
        if n_cpt > 0 and amount_per_cpt > 8000:
            reject_prob += 0.30
        reject_prob = min(reject_prob, 0.98)
        y[i] = int(rng.random() < reject_prob)

    return X, y


def _train_xgboost():
    """Train an XGBoost model on synthetic data and save it."""
    try:
        import xgboost as xgb
    except ImportError:
        logger.warning("xgboost not installed — cannot train model")
        return None

    logger.info("Training XGBoost rejection model on synthetic data …")
    X, y = _generate_synthetic_data()

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X, y)

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(_XGB_PATH))
    logger.info("XGBoost model saved to %s", _XGB_PATH)

    # Save feature importance for explainability
    importance = dict(zip(FEATURE_NAMES, [float(v) for v in model.feature_importances_], strict=False))
    (_MODEL_DIR / "xgb_feature_importance.json").write_text(json.dumps(importance, indent=2))

    return model


def _train_lightgbm():
    """Train a LightGBM model on synthetic data and save it."""
    try:
        import lightgbm as lgb
    except ImportError:
        logger.info("lightgbm not installed — skipping secondary model")
        return None

    logger.info("Training LightGBM rejection model on synthetic data …")
    X, y = _generate_synthetic_data(seed=99)

    model = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    model.fit(X, y)

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(_LGBM_PATH))
    logger.info("LightGBM model saved to %s", _LGBM_PATH)
    return model


def _optimize_and_save_ensemble_weights(xgb_model, lgbm_model):
    """Grid search to dynamically find optimal blending weights."""
    logger.info("Optimizing ensemble trust weights...")
    X_val, y_val = _generate_synthetic_data(n_samples=500, seed=123)
    xgb_preds = xgb_model.predict_proba(X_val)[:, 1]
    lgb_preds = lgbm_model.predict(X_val)
    
    best_acc = 0.0
    best_weight = 0.6
    for w in np.linspace(0.0, 1.0, 51):
        ensemble_preds = w * xgb_preds + (1.0 - w) * lgb_preds
        acc = float(np.mean((ensemble_preds > 0.5) == y_val))
        if acc > best_acc:
            best_acc = acc
            best_weight = float(w)
            
    logger.info("Optimal XGBoost trust score found: %.2f (Acc: %.2f)", best_weight, best_acc)
    (_MODEL_DIR / "ensemble_weights.json").write_text(json.dumps({"xgb_weight": best_weight}))
    return best_weight


def _load_models():
    """Load (or train) XGBoost + LightGBM models."""
    global _xgb_model, _lgbm_model, _models_load_attempted, _ensemble_xgb_weight
    if _models_load_attempted:
        return
    _models_load_attempted = True

    # --- XGBoost ---
    try:
        import xgboost as xgb
        if _XGB_PATH.exists():
            _xgb_model = xgb.XGBClassifier()
            _xgb_model.load_model(str(_XGB_PATH))
            logger.info("XGBoost model loaded from %s", _XGB_PATH)
        else:
            _xgb_model = _train_xgboost()
    except ImportError:
        logger.warning("xgboost not installed — will use heuristic fallback")
    except Exception:
        logger.warning("Failed to load/train XGBoost model", exc_info=True)

    # --- LightGBM ---
    try:
        import lightgbm as lgb
        if _LGBM_PATH.exists():
            if _validate_lightgbm_model_file(_LGBM_PATH, len(FEATURE_NAMES)):
                _lgbm_model = lgb.Booster(model_file=str(_LGBM_PATH))
                logger.info("LightGBM model loaded from %s", _LGBM_PATH)
            else:
                logger.warning(
                    "Skipping invalid LightGBM model at %s; using XGBoost/heuristic fallback",
                    _LGBM_PATH,
                )
        else:
            trained = _train_lightgbm()
            if trained is not None:
                if _validate_lightgbm_model_file(_LGBM_PATH, len(FEATURE_NAMES)):
                    _lgbm_model = trained.booster_
                else:
                    logger.warning("Trained LightGBM model failed validation; disabling LightGBM")
    except ImportError:
        logger.info("lightgbm not installed — skipping secondary model")
    except Exception:
        logger.warning("Failed to load/train LightGBM model", exc_info=True)

    # --- Ensemble Weights ---
    weights_path = _MODEL_DIR / "ensemble_weights.json"
    if weights_path.exists():
        try:
            _ensemble_xgb_weight = json.loads(weights_path.read_text()).get("xgb_weight", 0.6)
        except Exception:
            pass
    elif _xgb_model is not None and _lgbm_model is not None:
        _ensemble_xgb_weight = _optimize_and_save_ensemble_weights(_xgb_model, _lgbm_model)

# ------------------------------------------------------------------
# Reason explanation via feature importance
# ------------------------------------------------------------------

_FEATURE_REASON_MAP = {
    "has_patient_name": "Missing patient name",
    "has_policy_number": "Missing policy number",
    "has_diagnosis": "Missing diagnosis",
    "has_service_date": "Missing date of service",
    "has_total_amount": "Missing total amount",
    "has_provider": "Missing provider information",
    "num_parsed_fields": "Very few parsed fields — possible poor scan quality",
    "num_entities": "Few medical entities detected",
    "num_icd_codes": "No ICD-10 codes found",
    "num_cpt_codes": "No CPT codes found",
    "has_primary_icd": "No primary ICD code designated",
    "num_diagnosis_types": "No diagnosis entities",
    "total_amount_log": "Unusual claim amount",
    "amount_per_cpt_log": "Warning: Billed amount is suspiciously high compared to the provided procedures (possible overbilling)",
}


def _explain_prediction(features: dict[str, Any], score: float) -> list[dict[str, Any]]:
    """Generate human-readable reasons sorted by contribution."""
    reasons: list[dict[str, Any]] = []
    for fname in FEATURE_NAMES:
        val = features.get(fname, 0)
        # Flag missing critical booleans
        if fname.startswith("has_") and not val:
            reasons.append({
                "reason": _FEATURE_REASON_MAP.get(fname, fname),
                "feature": fname,
                "weight": 0.15,
            })
        elif fname in ("num_icd_codes", "num_cpt_codes") and val == 0:
            reasons.append({
                "reason": _FEATURE_REASON_MAP.get(fname, fname),
                "feature": fname,
                "weight": 0.10,
            })
        elif fname == "num_parsed_fields" and val < 3:
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.10,
            })
        elif fname == "amount_per_cpt_log" and val > np.log1p(8000):
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.30,
            })
    reasons.sort(key=lambda r: r["weight"], reverse=True)
    return reasons[:5]


# ------------------------------------------------------------------
# Public prediction API
# ------------------------------------------------------------------

def predict(features: dict[str, Any]) -> PredictionResult:
    """
    Score a claim for rejection risk.

    Uses XGBoost (primary) + LightGBM (ensemble) when available,
    with automatic fallback to a heuristic scorer.
    """
    _load_models()
    feat_array = _features_to_array(features).reshape(1, -1)

    # --- XGBoost prediction ---
    if _xgb_model is not None:
        try:
            xgb_proba = float(_xgb_model.predict_proba(feat_array)[0, 1])

            # Ensemble with LightGBM if available
            if _lgbm_model is not None:
                try:
                    lgbm_proba = float(_lgbm_model.predict(feat_array)[0])
                    #score =0.6  * xgb_proba + 0.4 * lgbm_proba
                    score = _ensemble_xgb_weight * xgb_proba + (1.0 - _ensemble_xgb_weight) * lgbm_proba
                    model_label = f"xgboost+lightgbm-ensemble(w={_ensemble_xgb_weight:.2f})"
                except Exception:
                    score = xgb_proba
                    model_label = "xgboost"
            else:
                score = xgb_proba
                model_label = "xgboost"

            score = round(min(max(score, 0.0), 1.0), 4)
            reasons = _explain_prediction(features, score)

            return PredictionResult(
                rejection_score=score,
                top_reasons=reasons,
                feature_vector=features,
                model_name=model_label,
                model_version=settings.model_version,
            )
        except Exception:
            logger.warning("XGBoost predict failed — falling back to heuristic", exc_info=True)

    # --- Heuristic fallback ---
    return _predict_heuristic(features)


def _predict_heuristic(features: dict[str, Any]) -> PredictionResult:
    """Rule-based scorer used when ML models are unavailable."""
    score = 0.0
    reasons: list[dict[str, Any]] = []

    critical = [
        ("has_patient_name", "Missing patient name", 0.15),
        ("has_policy_number", "Missing policy number", 0.15),
        ("has_diagnosis", "Missing diagnosis", 0.15),
        ("has_service_date", "Missing date of service", 0.15),
        ("has_total_amount", "Missing total amount", 0.15),
    ]
    for key, reason, weight in critical:
        if not features.get(key):
            score += weight
            reasons.append({"reason": reason, "weight": weight})

    if features.get("num_icd_codes", 0) == 0:
        score += 0.10
        reasons.append({"reason": "No ICD-10 codes found", "weight": 0.10})
    if features.get("num_cpt_codes", 0) == 0:
        score += 0.05
        reasons.append({"reason": "No CPT codes found", "weight": 0.05})
    if not features.get("has_primary_icd"):
        score += 0.05
        reasons.append({"reason": "No primary ICD code designated", "weight": 0.05})
    if features.get("num_parsed_fields", 0) < 3:
        score += 0.10
        reasons.append({"reason": "Very few parsed fields — possible poor scan quality", "weight": 0.10})

    score = round(min(score, 1.0), 4)
    reasons.sort(key=lambda r: r["weight"], reverse=True)

    return PredictionResult(
        rejection_score=score,
        top_reasons=reasons[:5],
        feature_vector=features,
        model_name="heuristic",
        model_version=settings.model_version,
    )
