# Predictor Service Improvements (v2.0)

This document outlines the major architectural, algorithmic, and performance improvements made to the ClaimGPT Predictor Service to handle complex medical claims accurately and robustly.

## 1. Algorithmic Overhaul: Two-Axis Scoring Model

The previous risk scoring heuristic suffered from a bias where **document completeness** heavily outweighed **clinical severity**. A perfectly documented, but highly critical claim (e.g., Cancer Bone Marrow Transplant) would incorrectly score as "Low Risk" (~7%), while a routine claim with a missing date might score "Medium Risk" (~45%).

### The Fix
We introduced a **Two-Axis Scoring Model** in `engine.py` (`_predict_heuristic`):

1. **Completeness Axis (0-60%)**: Penalties for missing critical fields (Name, Diagnosis, Dates, Amounts, Provider, ICD/CPT codes).
2. **Severity Axis (0-60%+)**: Additive risk scores based on clinical and financial intensity:
   - **Financial**: Very high claim amount (> ₹12L = +20%), High utilization of Sum Insured (> 80% = +20%).
   - **Clinical**: ICU admission (+15%), Extended Length of Stay (> 21 days = +18%), Multiple diagnoses (+10%), Complex coding (≥4 ICD codes = +8%), Surgery dominance (+10%), Blood transfusions (+6%).

**Crucial Logic Change:** The score reduction multiplier (which halves the risk score for clean claims) is now **only applied if the severity score is extremely low (< 10%)**. High-severity claims retain their high risk scores regardless of how perfectly they are documented.

## 2. Feature Engineering Enhancements (21 → 23 Features)

To support the new severity axis, the feature vector was expanded and refined:

*   **`has_blood_transfusion` (NEW)**: Detects if `blood_charges` > 0.
*   **`has_surgery` (NEW)**: Detects if `surgery_charges` or `ot_charges` > 0.
*   **`sum_insured` Fallback Extraction**: The parser often misses explicit `sum_insured` fields. A new regex fallback now scans all parsed field *values* for the pattern `"Sum Insured: Rs. X"` to ensure `claim_to_insured_ratio` is calculated correctly.
*   **Threshold Recalibration**: 
    *   Length of Stay (LOS) scoring now begins at ≥ 4 days (previously > 7).
    *   Age risk scoring now begins at > 50 years (previously > 65).
    *   CPT code complexity now begins at ≥ 2 procedures (previously ≥ 3).

## 3. Latency & Performance Optimization

To make the service production-ready without sacrificing accuracy, several micro-optimizations were implemented, reducing per-prediction latency to **< 0.1ms** (after initialization):

*   **Model Pre-loading**: Added an `@app.on_event("startup")` hook in `main.py` to trigger `_load_models()` when the FastAPI server starts. This eliminates the "cold start" latency spike on the first user request.
*   **Pre-compiled Regex & Dates**: The `_PAT_SUM_INSURED` regex and `_DATE_FORMATS` tuple are now compiled/defined globally at the module level in `engine.py`.
*   **Module-Level Imports**: Removed inline `import re` and `from datetime import datetime` calls from frequently executed functions (`_parse_date`, `build_features`) to eliminate per-call import overhead.

## 4. Synthetic Data Alignment

The synthetic data generator (`_generate_synthetic_data`) was updated to match the new 23-feature schema. This ensures that if the XGBoost or LightGBM models are re-trained locally (when no pre-trained weights are found), they learn the exact same severity indicators (blood, surgery, lower age/LOS thresholds) as the heuristic fallback.

## 5. Comprehensive Test Coverage (36 Tests)

A robust, standalone test suite (`tests/predictor/test_engine.py`) was created, completely decoupling it from database dependencies for rapid execution.

*   **Regression Archetypes**:
    1.  **LOW Risk**: Hernia claim (2-day stay, Age 40, ₹74K) → Expected < 25% (Scores ~3%).
    2.  **MEDIUM Risk**: Hysterectomy (6-day stay, Age 55, ₹2.09L, blood transfusion) → Expected 26-50% (Scores ~46%).
    3.  **HIGH Risk**: Cancer BMT (28-day ICU, Age 60, ₹13.5L, 4 ICD codes) → Expected > 50% (Scores ~87%).
*   **Edge Case Hardening**: Tests implemented to handle:
    *   Missing (`None`) or empty string values.
    *   Zero-amount claims and extreme outlier amounts (e.g., ₹99,99,999).
    *   Malformed dates and inverted dates (discharge before admission).
    *   Ages > 100 or non-numeric ages.
    *   Indian comma-formatted numbers (`1,50,000`).

## Summary of Impact

The predictor is now highly sensitive to clinical reality rather than just bureaucratic completeness. It handles edge cases gracefully, responds instantaneously in production, and provides granular, weighted reasons explaining exactly why a claim was categorized into a specific risk tier.
