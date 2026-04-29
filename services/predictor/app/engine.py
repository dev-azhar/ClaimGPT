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
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, date
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
    risk_category: str
    top_reasons: list[dict[str, Any]]
    feature_vector: dict[str, Any]
    model_name: str = settings.model_name
    model_version: str = settings.model_version


# ------------------------------------------------------------------
# Feature engineering (shared by all backends)
# ------------------------------------------------------------------

# Canonical field-alias map: predictor feature key → parser field names
# The predictor checks aliases in order and uses the first non-empty value.
_FIELD_ALIASES: dict[str, list[str]] = {
    "patient_name":  ["patient_name"],
    "policy_number": ["policy_number"],
    "diagnosis":     ["diagnosis", "primary_diagnosis"],
    "service_date":  ["service_date", "admission_date", "discharge_date",
                      "date_of_admission", "date_of_discharge", "dos"],
    "total_amount":  ["total_amount", "claimed_total", "calculated_total",
                      "net_amount", "grand_total"],
    "provider_name": ["provider_name", "hospital_name", "doctor_name",
                      "treating_doctor", "facility_name"],
    "sum_insured":   ["sum_insured", "cover_amount", "policy_sum"],
    "age":           ["age", "patient_age"],
    "admission_date":["admission_date", "date_of_admission", "doa"],
    "discharge_date":["discharge_date", "date_of_discharge", "dod"],
    "secondary_diagnosis": ["secondary_diagnosis", "comorbidity",
                            "additional_diagnosis"],
    "ward_type":     ["ward_type", "room_type"],
}

# Expense category fields the parser may emit
_EXPENSE_FIELDS = {
    "room_charges", "surgery_charges", "ot_charges", "anaesthesia_charges",
    "consultation_charges", "pharmacy_charges", "laboratory_charges",
    "radiology_charges", "consumables", "misc_charges", "nursing_charges",
    "icu_charges", "ambulance_charges", "investigation_charges",
    "surgeon_fees", "blood_charges", "physiotherapy_charges",
    "chemotherapy_charges", "transplant_charges", "isolation_charges",
    "other_charges",
}


def _resolve_field(field_map: dict[str, str | None], canonical: str) -> str | None:
    """Resolve a canonical field name through aliases, returning the first hit."""
    for alias in _FIELD_ALIASES.get(canonical, [canonical]):
        val = field_map.get(alias)
        if val:
            return val
    return None


def _parse_amount(raw: str | None) -> float:
    """Safely parse an Indian/international currency string to float."""
    if not raw:
        return 0.0
    try:
        return float(str(raw).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _compute_total_from_expenses(field_map: dict[str, str | None]) -> float:
    """Sum all expense category fields as fallback total."""
    total = 0.0
    for fname in _EXPENSE_FIELDS:
        val = _parse_amount(field_map.get(fname))
        if val > 0:
            total += val
    return total

# Pre-compiled patterns for latency
_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y",
                 "%d/%b/%Y", "%d.%m.%Y", "%m/%d/%Y", "%b %d, %Y")
_PAT_SUM_INSURED = re.compile(
    r"sum\s*insured\s*[:\-]?\s*(?:(?:rs|inr|\$)\.?\s*)?([\d,]+\.?\d*)", re.I
)


def _parse_date(raw: str | None) -> date | None:
    """Best-effort date parse, returns datetime.date or None."""
    if not raw:
        return None
    cleaned = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    # Last resort: try dateutil if available
    try:
        from dateutil.parser import parse as dateutil_parse
        return dateutil_parse(cleaned, dayfirst=True).date()
    except Exception:
        return None


# Canonical feature order — MUST match training order.
# Extended from 14 → 21 features with medical-context signals.
FEATURE_NAMES = [
    # --- Document completeness (6 binary) ---
    "has_patient_name",
    "has_policy_number",
    "has_diagnosis",
    "has_service_date",
    "has_total_amount",
    "has_provider",
    # --- Counts ---
    "num_parsed_fields",
    "num_entities",
    "num_icd_codes",
    "num_cpt_codes",
    "has_primary_icd",
    "num_diagnosis_types",
    # --- Financial ---
    "total_amount_log",
    "amount_per_cpt_log",
    # --- Medical context ---
    "patient_age_norm",         # age / 100, clipped to [0, 1]
    "length_of_stay",           # days, clipped to [0, 60]
    "claim_to_insured_ratio",   # total_amount / sum_insured, clipped [0, 1]
    "num_expense_categories",   # count of non-zero charge fields
    "is_icu_admission",         # 1 if ICU charges present or ward_type=ICU
    "has_secondary_diagnosis",  # 1 if secondary diagnosis exists
    "surgery_cost_ratio",       # surgery_charges / total_amount, clipped [0, 1]
    "has_blood_transfusion",    # 1 if blood_charges present
    "has_surgery",              # 1 if surgery_charges or ot_charges present
]


def build_features(
    parsed_fields: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    codes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a feature vector from upstream pipeline data.

    Uses canonical field-alias mapping so that parser field names
    (e.g. ``admission_date``, ``hospital_name``) are correctly resolved
    to the predictor's expected features (``has_service_date``,
    ``has_provider``).
    """
    field_map: dict[str, str | None] = {
        f["field_name"]: f.get("field_value") for f in parsed_fields
    }

    # --- Resolve canonical fields through aliases ---
    has_service_date = int(bool(_resolve_field(field_map, "service_date")))
    has_total_amount_raw = _resolve_field(field_map, "total_amount")
    has_provider = int(bool(_resolve_field(field_map, "provider_name")))

    # --- Compute total amount (explicit or summed from categories) ---
    amount_val = _parse_amount(has_total_amount_raw)
    if amount_val <= 0:
        amount_val = _compute_total_from_expenses(field_map)
    has_total_amount = int(amount_val > 0)

    # --- ICD/CPT: use coding service data, fall back to parsed fields ---
    num_icd_from_codes = sum(1 for c in codes if c.get("code_system") == "ICD10")
    num_cpt_from_codes = sum(1 for c in codes if c.get("code_system") == "CPT")

    # Fallback: count ICD/CPT from parser's own extracted fields
    if num_icd_from_codes == 0:
        num_icd_from_codes = sum(
            1 for f in parsed_fields if f.get("field_name") == "icd_code" and f.get("field_value")
        )
    if num_cpt_from_codes == 0:
        num_cpt_from_codes = sum(
            1 for f in parsed_fields if f.get("field_name") == "cpt_code" and f.get("field_value")
        )

    has_primary_icd = int(any(
        c.get("is_primary") and c.get("code_system") == "ICD10" for c in codes
    ))
    # If coding service didn't mark a primary but ICD codes exist, treat first as primary
    if not has_primary_icd and num_icd_from_codes > 0:
        has_primary_icd = 1

    # --- Medical context features ---
    age_raw = _resolve_field(field_map, "age")
    try:
        age_val = float(str(age_raw).strip()) if age_raw else 0.0
    except (ValueError, TypeError):
        age_val = 0.0
    patient_age_norm = min(max(age_val / 100.0, 0.0), 1.0)

    adm_date = _parse_date(_resolve_field(field_map, "admission_date"))
    dis_date = _parse_date(_resolve_field(field_map, "discharge_date"))
    if adm_date and dis_date and dis_date >= adm_date:
        length_of_stay = float(min((dis_date - adm_date).days, 60))
    else:
        length_of_stay = 0.0

    sum_insured_raw = _resolve_field(field_map, "sum_insured")
    sum_insured_val = _parse_amount(sum_insured_raw)
    # Fallback: scan all parsed field values for "Sum Insured: Rs. X" pattern
    if sum_insured_val <= 0:
        for f in parsed_fields:
            val = f.get("field_value") or ""
            m = _PAT_SUM_INSURED.search(val)
            if m:
                sum_insured_val = _parse_amount(m.group(1))
                if sum_insured_val > 0:
                    break
    if sum_insured_val > 0:
        claim_to_insured = min(amount_val / sum_insured_val, 1.0)
    else:
        claim_to_insured = 0.0

    num_expense_cats = sum(
        1 for fn in _EXPENSE_FIELDS if _parse_amount(field_map.get(fn)) > 0
    )

    icu_charges = _parse_amount(field_map.get("icu_charges"))
    ward_type = (field_map.get("ward_type") or "").lower()
    is_icu = int(icu_charges > 0 or "icu" in ward_type)

    # Count ALL secondary diagnosis entries (parser can emit multiple)
    num_secondary = sum(
        1 for f in parsed_fields
        if f.get("field_name") == "secondary_diagnosis" and f.get("field_value")
    )
    has_secondary = int(num_secondary > 0)

    surgery_charges = _parse_amount(field_map.get("surgery_charges"))
    ot_charges = _parse_amount(field_map.get("ot_charges"))
    surgery_cost_ratio = min(surgery_charges / max(amount_val, 1.0), 1.0)
    has_surgery = int(surgery_charges > 0 or ot_charges > 0)

    blood_charges = _parse_amount(field_map.get("blood_charges"))
    has_blood_transfusion = int(blood_charges > 0)

    num_cpt_total = max(num_cpt_from_codes, 1)

    return {
        # Document completeness
        "has_patient_name":  int(bool(_resolve_field(field_map, "patient_name"))),
        "has_policy_number": int(bool(_resolve_field(field_map, "policy_number"))),
        "has_diagnosis":     int(bool(_resolve_field(field_map, "diagnosis"))),
        "has_service_date":  has_service_date,
        "has_total_amount":  has_total_amount,
        "has_provider":      has_provider,
        # Counts
        "num_parsed_fields": len(parsed_fields),
        "num_entities":      len(entities),
        "num_icd_codes":     num_icd_from_codes,
        "num_cpt_codes":     num_cpt_from_codes,
        "has_primary_icd":   has_primary_icd,
        "num_diagnosis_types": len({
            str(e.get("entity_text", "")).strip().lower() 
            for e in entities 
            if e.get("entity_type") == "DIAGNOSIS" and str(e.get("entity_text", "")).strip()
        }),
        # Financial
        "total_amount_log":     float(np.log1p(amount_val)),
        "amount_per_cpt_log":   float(np.log1p(amount_val / num_cpt_total)),
        # Medical context
        "patient_age_norm":         patient_age_norm,
        "length_of_stay":           length_of_stay,
        "claim_to_insured_ratio":   claim_to_insured,
        "num_expense_categories":   float(num_expense_cats),
        "is_icu_admission":         is_icu,
        "has_secondary_diagnosis":  has_secondary,
        "surgery_cost_ratio":       surgery_cost_ratio,
        "has_blood_transfusion":    has_blood_transfusion,
        "has_surgery":              has_surgery,
    }


def _features_to_array(features: dict[str, Any]) -> np.ndarray:
    """Convert feature dict → 1-D numpy array in canonical order."""
    return np.array([float(features.get(f, 0)) for f in FEATURE_NAMES], dtype=np.float32)


def _score_to_category(score: float) -> str:
    """Map a 0–1 rejection score to a human-readable risk category."""
    if score <= 0.25:
        return "LOW"
    elif score <= 0.50:
        return "MEDIUM"
    else:
        return "HIGH"


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


def _generate_synthetic_data(n_samples: int = 3000, seed: int = 42):
    """
    Generate synthetic claim feature vectors + labels for initial training.

    Produces vectors matching the 21-feature FEATURE_NAMES with realistic
    medical claim distributions.  Calibrated so that clean, complete,
    low-complexity claims get ~5-15% rejection probability while claims
    with missing fields or suspicious patterns score 50%+.
    """
    rng = np.random.RandomState(seed)
    n_feat = len(FEATURE_NAMES)
    X = np.zeros((n_samples, n_feat), dtype=np.float32)
    y = np.zeros(n_samples, dtype=np.int32)

    for i in range(n_samples):
        # --- Document completeness (mostly present in real claims) ---
        has_name     = rng.choice([0, 1], p=[0.03, 0.97])
        has_policy   = rng.choice([0, 1], p=[0.05, 0.95])
        has_diag     = rng.choice([0, 1], p=[0.06, 0.94])
        has_date     = rng.choice([0, 1], p=[0.04, 0.96])
        has_amount   = rng.choice([0, 1], p=[0.05, 0.95])
        has_provider = rng.choice([0, 1], p=[0.06, 0.94])

        # --- Counts ---
        n_fields     = rng.randint(8, 40)
        n_ents       = rng.randint(0, 12)
        n_icd        = rng.randint(0, 5)
        n_cpt        = rng.randint(0, 4)
        has_pri      = int(n_icd > 0 and rng.random() > 0.15)
        n_diag_types = min(n_ents, rng.randint(0, 3))

        # --- Financial ---
        amount       = rng.lognormal(10.0, 1.2)  # median ~₹22k, realistic Indian claims
        amount_log   = float(np.log1p(amount))
        cpt_denom    = max(1, n_cpt)
        amt_per_cpt  = float(np.log1p(amount / cpt_denom))

        # --- Medical context ---
        age          = max(0, min(100, rng.normal(42, 18)))
        age_norm     = age / 100.0
        los          = float(rng.choice([1, 2, 3, 5, 7, 10, 14, 21, 30],
                                        p=[0.15, 0.25, 0.20, 0.15, 0.10, 0.06, 0.04, 0.03, 0.02]))
        sum_insured  = rng.choice([100000, 200000, 300000, 400000, 500000, 1000000],
                                  p=[0.10, 0.15, 0.20, 0.25, 0.20, 0.10])
        claim_ratio  = min(amount / max(sum_insured, 1.0), 1.0)
        n_exp_cats   = float(rng.randint(3, 12))
        is_icu       = rng.choice([0, 1], p=[0.80, 0.20])
        has_sec_diag = rng.choice([0, 1], p=[0.60, 0.40])
        surg_ratio   = rng.beta(2, 5) if has_amount else 0.0
        has_blood    = rng.choice([0, 1], p=[0.85, 0.15])
        has_surg     = rng.choice([0, 1], p=[0.40, 0.60])

        X[i] = [
            has_name, has_policy, has_diag, has_date, has_amount,
            has_provider, n_fields, n_ents, n_icd, n_cpt,
            has_pri, n_diag_types, amount_log, amt_per_cpt,
            age_norm, los, claim_ratio, n_exp_cats,
            is_icu, has_sec_diag, surg_ratio,
            has_blood, has_surg,
        ]

        # --- Rejection probability: two-axis (completeness + severity) ---
        reject_prob = 0.05  # clean-claim baseline

        # AXIS 1: Missing critical fields
        missing = sum(1 for v in [has_name, has_policy, has_diag, has_date, has_amount] if v == 0)
        reject_prob += missing * 0.12

        if n_icd == 0:
            reject_prob += 0.05
        if not has_pri and n_icd > 0:
            reject_prob += 0.03
        if n_fields < 5:
            reject_prob += 0.06

        # AXIS 2: Medical & financial severity
        if amount > 1200000:       # > 12 lakh
            reject_prob += 0.20
        elif amount > 440000:      # > 4.4 lakh
            reject_prob += 0.12
        elif amount > 100000:      # > 1 lakh
            reject_prob += 0.05

        if claim_ratio > 0.80:
            reject_prob += 0.20
        elif claim_ratio > 0.50:
            reject_prob += 0.10

        if los > 21:
            reject_prob += 0.18
        elif los > 14:
            reject_prob += 0.12
        elif los > 7:
            reject_prob += 0.08
        elif los >= 4:
            reject_prob += 0.05

        if is_icu:
            reject_prob += 0.15

        if has_surg:
            if surg_ratio > 0.50:
                reject_prob += 0.10
            elif surg_ratio > 0.25:
                reject_prob += 0.06
            else:
                reject_prob += 0.03

        if has_blood:
            reject_prob += 0.06

        if has_sec_diag:
            reject_prob += 0.10

        if n_icd >= 4:
            reject_prob += 0.08
        elif n_icd >= 2:
            reject_prob += 0.04

        if age > 65:
            reject_prob += 0.08
        elif age > 50:
            reject_prob += 0.04
        elif age < 5:
            reject_prob += 0.06

        if n_cpt >= 3:
            reject_prob += 0.06
        elif n_cpt >= 2:
            reject_prob += 0.03

        # Only reduce for simple, complete claims
        severity = sum([
            int(amount > 100000), int(los > 7), int(is_icu),
            int(has_sec_diag), int(claim_ratio > 0.50), int(age > 65),
        ])
        if missing == 0 and severity == 0 and n_fields >= 15:
            reject_prob *= 0.4  # strong reduction for simple clean claims

        reject_prob = min(max(reject_prob, 0.02), 0.95)
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
    "has_service_date": "Missing date of service / admission date",
    "has_total_amount": "Missing total amount (no charges found)",
    "has_provider": "Missing provider / hospital information",
    "num_parsed_fields": "Very few parsed fields — possible poor scan quality",
    "num_entities": "Few medical entities detected",
    "num_icd_codes": "No ICD-10 codes found",
    "num_cpt_codes": "No CPT codes found",
    "has_primary_icd": "No primary ICD code designated",
    "num_diagnosis_types": "No diagnosis entities",
    "total_amount_log": "Unusual claim amount",
    "amount_per_cpt_log": "Billed amount is high relative to procedures (possible overbilling)",
    "patient_age_norm": "Patient age is in a high-risk band",
    "length_of_stay": "Extended hospital stay",
    "claim_to_insured_ratio": "Claim amount is a large portion of sum insured",
    "num_expense_categories": "Many diverse expense categories",
    "is_icu_admission": "ICU admission detected",
    "has_secondary_diagnosis": "Multiple diagnoses / comorbidities present",
    "surgery_cost_ratio": "Surgery cost dominates total bill",
    "has_blood_transfusion": "Blood transfusion required",
    "has_surgery": "Surgical procedure performed",
}

# Features that are severity indicators, NOT document-completeness flags.
# Missing these should NOT be treated as a penalty.
_SEVERITY_FEATURES = {"has_secondary_diagnosis", "has_blood_transfusion", "has_surgery"}


def _explain_prediction(features: dict[str, Any], score: float) -> list[dict[str, Any]]:
    """Generate human-readable reasons sorted by contribution."""
    reasons: list[dict[str, Any]] = []
    for fname in FEATURE_NAMES:
        val = features.get(fname, 0)
        # Flag missing critical booleans (but NOT severity indicators)
        if fname.startswith("has_") and fname not in _SEVERITY_FEATURES and not val:
            reasons.append({
                "reason": _FEATURE_REASON_MAP.get(fname, fname),
                "feature": fname,
                "weight": 0.15,
            })
        elif fname in ("num_icd_codes", "num_cpt_codes") and val == 0:
            reasons.append({
                "reason": _FEATURE_REASON_MAP.get(fname, fname),
                "feature": fname,
                "weight": 0.08,
            })
        elif fname == "num_parsed_fields" and val < 5:
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.10,
            })
        elif fname == "claim_to_insured_ratio" and val > 0.80:
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.15,
            })
        elif fname == "length_of_stay" and val > 14:
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.08,
            })
        elif fname == "patient_age_norm" and (val < 0.05 or val > 0.75):
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.05,
            })
        elif fname == "is_icu_admission" and val:
            reasons.append({
                "reason": _FEATURE_REASON_MAP[fname],
                "feature": fname,
                "weight": 0.04,
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
                risk_category=_score_to_category(score),
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
    """Two-axis scorer: document completeness + medical/financial severity.

    The final score is the combination of:
      * **Completeness risk** (0-0.60): missing fields, codes, etc.
      * **Severity risk** (0-0.60): ICU, long stay, high amount, age, diagnoses

    Both axes contribute additively. A well-documented but medically
    complex claim (e.g. bone marrow transplant) should score HIGH,
    while a well-documented simple claim (e.g. hernia repair) scores LOW.
    """
    completeness_score = 0.0
    severity_score = 0.0
    reasons: list[dict[str, Any]] = []

    # ========== AXIS 1: Document Completeness ==========
    critical = [
        ("has_patient_name", "Missing patient name", 0.08),
        ("has_policy_number", "Missing policy number", 0.08),
        ("has_diagnosis", "Missing diagnosis", 0.12),
        ("has_service_date", "Missing date of service / admission date", 0.08),
        ("has_total_amount", "Missing total amount (no charges found)", 0.10),
    ]
    for key, reason, weight in critical:
        if not features.get(key):
            completeness_score += weight
            reasons.append({"reason": reason, "weight": weight})

    if features.get("num_icd_codes", 0) == 0:
        completeness_score += 0.05
        reasons.append({"reason": "No ICD-10 codes found", "weight": 0.05})
    if not features.get("has_primary_icd"):
        completeness_score += 0.03
        reasons.append({"reason": "No primary ICD code designated", "weight": 0.03})
    if features.get("num_parsed_fields", 0) < 5:
        completeness_score += 0.06
        reasons.append({"reason": "Very few parsed fields", "weight": 0.06})

    # ========== AXIS 2: Medical & Financial Severity ==========

    # --- Claim amount magnitude ---
    amount_log = features.get("total_amount_log", 0)
    # log1p(500000) ~ 13.1, log1p(200000) ~ 12.2, log1p(100000) ~ 11.5
    if amount_log > 14.0:       # > ~12 lakh
        severity_score += 0.20
        reasons.append({"reason": "Very high claim amount", "weight": 0.20})
    elif amount_log > 13.0:     # > ~4.4 lakh
        severity_score += 0.12
        reasons.append({"reason": "High claim amount", "weight": 0.12})
    elif amount_log > 11.5:     # > ~1 lakh
        severity_score += 0.08
        reasons.append({"reason": "Significant claim amount", "weight": 0.08})

    # --- Claim-to-insured ratio ---
    claim_ratio = features.get("claim_to_insured_ratio", 0)
    if claim_ratio > 0.80:
        severity_score += 0.20
        reasons.append({"reason": "Claim exceeds 80% of sum insured", "weight": 0.20})
    elif claim_ratio > 0.50:
        severity_score += 0.12
        reasons.append({"reason": "Claim exceeds 50% of sum insured", "weight": 0.12})
    elif claim_ratio > 0.30:
        severity_score += 0.05
        reasons.append({"reason": "Notable sum insured utilization", "weight": 0.05})

    # --- Length of stay ---
    los = features.get("length_of_stay", 0)
    if los > 21:
        severity_score += 0.18
        reasons.append({"reason": f"Very long hospital stay ({int(los)} days)", "weight": 0.18})
    elif los > 14:
        severity_score += 0.12
        reasons.append({"reason": f"Extended hospital stay ({int(los)} days)", "weight": 0.12})
    elif los > 7:
        severity_score += 0.08
        reasons.append({"reason": f"Notable hospital stay ({int(los)} days)", "weight": 0.08})
    elif los >= 4:
        severity_score += 0.05
        reasons.append({"reason": f"Multi-day hospital stay ({int(los)} days)", "weight": 0.05})

    # --- ICU admission ---
    if features.get("is_icu_admission"):
        severity_score += 0.15
        reasons.append({"reason": "ICU admission detected", "weight": 0.15})

    # --- Surgical case ---
    if features.get("has_surgery"):
        surg_ratio = features.get("surgery_cost_ratio", 0)
        if surg_ratio > 0.50:
            severity_score += 0.10
            reasons.append({"reason": "Major surgical procedure (surgery-dominant bill)", "weight": 0.10})
        elif surg_ratio > 0.25:
            severity_score += 0.06
            reasons.append({"reason": "Surgical procedure performed", "weight": 0.06})
        else:
            severity_score += 0.03
            reasons.append({"reason": "Minor surgical/OT component", "weight": 0.03})

    # --- Blood transfusion ---
    if features.get("has_blood_transfusion"):
        severity_score += 0.06
        reasons.append({"reason": "Blood transfusion required", "weight": 0.06})

    # --- Multiple diagnoses / comorbidities ---
    if features.get("has_secondary_diagnosis"):
        severity_score += 0.10
        reasons.append({"reason": "Multiple diagnoses / comorbidities present", "weight": 0.10})

    # --- Multiple ICD codes (complexity) ---
    n_icd = features.get("num_icd_codes", 0)
    if n_icd >= 4:
        severity_score += 0.08
        reasons.append({"reason": f"Complex case: {n_icd} ICD codes", "weight": 0.08})
    elif n_icd >= 2:
        severity_score += 0.04
        reasons.append({"reason": f"Multiple ICD codes ({n_icd})", "weight": 0.04})

    # --- Age risk ---
    age_norm = features.get("patient_age_norm", 0)
    if age_norm > 0.65:
        severity_score += 0.08
        reasons.append({"reason": "Elderly patient (higher complication risk)", "weight": 0.08})
    elif age_norm > 0.50:
        severity_score += 0.04
        reasons.append({"reason": "Middle-aged patient (moderate risk band)", "weight": 0.04})
    elif 0 < age_norm < 0.05:
        severity_score += 0.06
        reasons.append({"reason": "Very young patient (paediatric risk)", "weight": 0.06})

    # --- Multiple procedures ---
    n_cpt = features.get("num_cpt_codes", 0)
    if n_cpt >= 3:
        severity_score += 0.06
        reasons.append({"reason": f"Multiple procedures ({n_cpt} CPT codes)", "weight": 0.06})
    elif n_cpt >= 2:
        severity_score += 0.03
        reasons.append({"reason": f"Two procedures performed", "weight": 0.03})

    # ========== COMBINE AXES ==========
    score = completeness_score + severity_score

    # Only reduce for truly simple, complete claims (no severity signals)
    missing_count = sum(1 for k, _, _ in critical if not features.get(k))
    if missing_count == 0 and severity_score < 0.10:
        score *= 0.5

    score = round(min(max(score, 0.0), 1.0), 4)
    reasons.sort(key=lambda r: r["weight"], reverse=True)

    return PredictionResult(
        rejection_score=score,
        risk_category=_score_to_category(score),
        top_reasons=reasons[:5],
        feature_vector=features,
        model_name="heuristic",
        model_version=settings.model_version,
    )
