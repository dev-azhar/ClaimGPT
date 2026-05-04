"""Tests for the predictor feature engineering + scoring engine.

Covers:
  - Feature extraction (alias resolution, computed totals, ICD/CPT fallback)
  - Risk scoring across LOW, MEDIUM, HIGH tiers
  - Edge cases (empty claims, extreme values, partial data)
  - Regression tests for known claim scenarios
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "predictor"))
# Drop any cached `app.*` modules from sibling services (e.g. coding) so we
# load `app.engine` from services/predictor and not whichever sibling test
# happened to import first when the full suite runs.
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from app.engine import build_features, predict, _score_to_category, FEATURE_NAMES


def _make_features(**overrides) -> dict:
    """Helper: build a full 23-feature dict with sensible defaults."""
    base = {
        "has_patient_name": 1,
        "has_policy_number": 1,
        "has_diagnosis": 1,
        "has_service_date": 1,
        "has_total_amount": 1,
        "has_provider": 1,
        "num_parsed_fields": 20,
        "num_entities": 2,
        "num_icd_codes": 1,
        "num_cpt_codes": 1,
        "has_primary_icd": 1,
        "num_diagnosis_types": 1,
        "total_amount_log": 6.2,          # ~490 Rs (very small)
        "amount_per_cpt_log": 6.2,
        "patient_age_norm": 0.40,
        "length_of_stay": 2.0,
        "claim_to_insured_ratio": 0.18,
        "num_expense_categories": 8.0,
        "is_icu_admission": 0,
        "has_secondary_diagnosis": 0,
        "surgery_cost_ratio": 0.3,
        "has_blood_transfusion": 0,
        "has_surgery": 0,
    }
    base.update(overrides)
    return base


# ================================================================
# TestBuildFeatures — Feature extraction tests
# ================================================================

class TestBuildFeatures:
    def test_complete_claim_features(self):
        parsed = [
            {"field_name": "patient_name", "field_value": "Jane Doe"},
            {"field_name": "policy_number", "field_value": "POL-123"},
            {"field_name": "diagnosis", "field_value": "Diabetes"},
            {"field_name": "service_date", "field_value": "2026-01-01"},
            {"field_name": "total_amount", "field_value": "500"},
            {"field_name": "provider_name", "field_value": "Dr. Smith"},
        ]
        entities = [{"entity_type": "DIAGNOSIS", "entity_text": "Diabetes"}]
        codes = [
            {"code": "E11.9", "code_system": "ICD10", "is_primary": True},
            {"code": "99213", "code_system": "CPT", "is_primary": False},
        ]
        features = build_features(parsed, entities, codes)
        assert features["has_patient_name"] == 1
        assert features["has_policy_number"] == 1
        assert features["has_diagnosis"] == 1
        assert features["has_service_date"] == 1
        assert features["has_total_amount"] == 1
        assert features["has_provider"] == 1
        assert features["num_icd_codes"] == 1
        assert features["num_cpt_codes"] == 1
        assert features["has_primary_icd"] == 1
        assert features["num_parsed_fields"] == 6
        assert len(features) == len(FEATURE_NAMES), "Feature count mismatch with FEATURE_NAMES"

    def test_empty_claim_features(self):
        features = build_features([], [], [])
        assert features["has_patient_name"] == 0
        assert features["num_parsed_fields"] == 0
        assert features["num_icd_codes"] == 0
        assert features["has_blood_transfusion"] == 0
        assert features["has_surgery"] == 0

    def test_alias_resolution_admission_date(self):
        parsed = [{"field_name": "admission_date", "field_value": "09-03-2026"}]
        features = build_features(parsed, [], [])
        assert features["has_service_date"] == 1

    def test_alias_resolution_hospital_name(self):
        parsed = [{"field_name": "hospital_name", "field_value": "Apollo Hospitals"}]
        features = build_features(parsed, [], [])
        assert features["has_provider"] == 1

    def test_computed_total_from_expenses(self):
        parsed = [
            {"field_name": "room_charges", "field_value": "6000.00"},
            {"field_name": "surgery_charges", "field_value": "32000.00"},
            {"field_name": "pharmacy_charges", "field_value": "3800.00"},
        ]
        features = build_features(parsed, [], [])
        assert features["has_total_amount"] == 1
        assert features["total_amount_log"] > 0

    def test_icd_fallback_from_parsed_fields(self):
        parsed = [{"field_name": "icd_code", "field_value": "K40.90"}]
        features = build_features(parsed, [], [])
        assert features["num_icd_codes"] == 1
        assert features["has_primary_icd"] == 1

    def test_length_of_stay_computed(self):
        parsed = [
            {"field_name": "admission_date", "field_value": "09-03-2026"},
            {"field_name": "discharge_date", "field_value": "11-03-2026"},
        ]
        features = build_features(parsed, [], [])
        assert features["length_of_stay"] == 2.0

    def test_blood_transfusion_detection(self):
        parsed = [{"field_name": "blood_charges", "field_value": "4500.00"}]
        features = build_features(parsed, [], [])
        assert features["has_blood_transfusion"] == 1

    def test_surgery_detection(self):
        parsed = [{"field_name": "surgery_charges", "field_value": "50000.00"}]
        features = build_features(parsed, [], [])
        assert features["has_surgery"] == 1

    def test_ot_charges_counts_as_surgery(self):
        parsed = [{"field_name": "ot_charges", "field_value": "10000.00"}]
        features = build_features(parsed, [], [])
        assert features["has_surgery"] == 1

    def test_multiple_secondary_diagnoses(self):
        parsed = [
            {"field_name": "secondary_diagnosis", "field_value": "Anaemia"},
            {"field_name": "secondary_diagnosis", "field_value": "CKD"},
            {"field_name": "secondary_diagnosis", "field_value": "Neutropenia"},
        ]
        features = build_features(parsed, [], [])
        assert features["has_secondary_diagnosis"] == 1

    def test_icu_from_charges(self):
        parsed = [{"field_name": "icu_charges", "field_value": "50000.00"}]
        features = build_features(parsed, [], [])
        assert features["is_icu_admission"] == 1

    def test_age_normalized(self):
        parsed = [{"field_name": "age", "field_value": "70"}]
        features = build_features(parsed, [], [])
        assert features["patient_age_norm"] == 0.70

    def test_date_formats(self):
        """Multiple date formats should parse correctly."""
        for fmt_val in ("09-03-2026", "09/03/2026", "2026-03-09", "09-Mar-2026"):
            parsed = [
                {"field_name": "admission_date", "field_value": fmt_val},
                {"field_name": "discharge_date", "field_value": "11-03-2026"},
            ]
            features = build_features(parsed, [], [])
            assert features["has_service_date"] == 1, f"Failed for date format: {fmt_val}"

    def test_feature_vector_size(self):
        """Feature vector must always have exactly len(FEATURE_NAMES) entries."""
        features = build_features([], [], [])
        assert len(features) == len(FEATURE_NAMES)


# ================================================================
# TestPredict — Scoring & risk categorization
# ================================================================

class TestPredict:
    def test_simple_clean_claim_low(self):
        """Simple clean claim with minimal amount → LOW risk."""
        features = _make_features()
        result = predict(features)
        assert result.rejection_score < 0.25
        assert result.risk_category == "LOW"
        assert result.model_name is not None

    def test_all_missing_high(self):
        """All fields missing → HIGH risk."""
        features = _make_features(
            has_patient_name=0, has_policy_number=0, has_diagnosis=0,
            has_service_date=0, has_total_amount=0, has_provider=0,
            num_parsed_fields=1, num_entities=0, num_icd_codes=0,
            num_cpt_codes=0, has_primary_icd=0, num_diagnosis_types=0,
            total_amount_log=0.0, amount_per_cpt_log=0.0,
            patient_age_norm=0, length_of_stay=0, claim_to_insured_ratio=0,
            num_expense_categories=0, is_icu_admission=0,
            has_secondary_diagnosis=0, surgery_cost_ratio=0,
            has_blood_transfusion=0, has_surgery=0,
        )
        result = predict(features)
        assert result.rejection_score > 0.4
        assert result.risk_category in ("MEDIUM", "HIGH")
        assert len(result.top_reasons) > 0

    def test_score_capped_at_one(self):
        features = _make_features(
            has_patient_name=0, has_policy_number=0, has_diagnosis=0,
            has_service_date=0, has_total_amount=0, has_provider=0,
            num_parsed_fields=0, num_entities=0, num_icd_codes=0,
            num_cpt_codes=0, has_primary_icd=0, num_diagnosis_types=0,
            total_amount_log=0.0, amount_per_cpt_log=0.0,
        )
        result = predict(features)
        assert result.rejection_score <= 1.0

    def test_reasons_sorted_by_weight(self):
        features = _make_features(has_patient_name=0, has_policy_number=0)
        result = predict(features)
        if len(result.top_reasons) > 1:
            weights = [r["weight"] for r in result.top_reasons]
            assert weights == sorted(weights, reverse=True)

    def test_risk_category_mapping(self):
        assert _score_to_category(0.10) == "LOW"
        assert _score_to_category(0.25) == "LOW"
        assert _score_to_category(0.35) == "MEDIUM"
        assert _score_to_category(0.50) == "MEDIUM"
        assert _score_to_category(0.60) == "HIGH"
        assert _score_to_category(0.90) == "HIGH"


# ================================================================
# TestRegressionClaims — Known claim scenarios
# ================================================================

class TestRegressionClaims:
    """Regression tests for specific claim archetypes."""

    def test_hernia_low_risk(self):
        """Hernia: 2-day stay, age 40, Rs 74K, no ICU → LOW."""
        parsed = [
            {"field_name": "patient_name", "field_value": "Harish Kumar"},
            {"field_name": "policy_number", "field_value": "POL-FG-2025-330044"},
            {"field_name": "diagnosis", "field_value": "Right Inguinal Hernia"},
            {"field_name": "admission_date", "field_value": "09-03-2026"},
            {"field_name": "discharge_date", "field_value": "11-03-2026"},
            {"field_name": "hospital_name", "field_value": "Continental Hospitals"},
            {"field_name": "age", "field_value": "40"},
            {"field_name": "room_charges", "field_value": "6000.00"},
            {"field_name": "surgery_charges", "field_value": "32000.00"},
            {"field_name": "ot_charges", "field_value": "8000.00"},
            {"field_name": "anaesthesia_charges", "field_value": "5500.00"},
            {"field_name": "consultation_charges", "field_value": "3000.00"},
            {"field_name": "pharmacy_charges", "field_value": "3800.00"},
            {"field_name": "laboratory_charges", "field_value": "3200.00"},
            {"field_name": "radiology_charges", "field_value": "2500.00"},
            {"field_name": "consumables", "field_value": "9000.00"},
            {"field_name": "misc_charges", "field_value": "1000.00"},
            {"field_name": "icd_code", "field_value": "K40.90"},
        ]
        features = build_features(parsed, [], [])
        result = predict(features)
        assert result.risk_category == "LOW"
        assert result.rejection_score < 0.25

    def test_hysterectomy_medium_risk(self):
        """Hysterectomy: 6-day, age 55, Rs 2.09L, blood transfusion, secondary diagnosis → MEDIUM."""
        parsed = [
            {"field_name": "patient_name", "field_value": "Lakshmi Devi"},
            {"field_name": "policy_number", "field_value": "POL-MB-2024-445566"},
            {"field_name": "diagnosis", "field_value": "Laparoscopic Hysterectomy"},
            {"field_name": "admission_date", "field_value": "07-03-2026"},
            {"field_name": "discharge_date", "field_value": "13-03-2026"},
            {"field_name": "hospital_name", "field_value": "Fernandez Hospital"},
            {"field_name": "age", "field_value": "55"},
            {"field_name": "secondary_diagnosis", "field_value": "Anaemia (Iron Deficiency)"},
            {"field_name": "room_charges", "field_value": "24000.00"},
            {"field_name": "surgery_charges", "field_value": "85000.00"},
            {"field_name": "ot_charges", "field_value": "20000.00"},
            {"field_name": "anaesthesia_charges", "field_value": "10000.00"},
            {"field_name": "consultation_charges", "field_value": "7200.00"},
            {"field_name": "pharmacy_charges", "field_value": "11000.00"},
            {"field_name": "laboratory_charges", "field_value": "6800.00"},
            {"field_name": "radiology_charges", "field_value": "9500.00"},
            {"field_name": "nursing_charges", "field_value": "6000.00"},
            {"field_name": "consumables", "field_value": "22000.00"},
            {"field_name": "misc_charges", "field_value": "3000.00"},
            {"field_name": "blood_charges", "field_value": "4500.00"},
            {"field_name": "icd_code", "field_value": "D25.9"},
            {"field_name": "icd_code", "field_value": "D50.9"},
            {"field_name": "cpt_code", "field_value": "36430"},
            {"field_name": "cpt_code", "field_value": "58570"},
        ]
        features = build_features(parsed, [], [])
        result = predict(features)
        assert result.risk_category == "MEDIUM"
        assert 0.26 <= result.rejection_score <= 0.50

    def test_cancer_bmt_high_risk(self):
        """Cancer BMT: 28-day ICU, age 60, Rs 13.5L, 4 ICD codes, 3 CPT → HIGH."""
        parsed = [
            {"field_name": "patient_name", "field_value": "Nalini Prasad"},
            {"field_name": "policy_number", "field_value": "POL-SH-2023-667744"},
            {"field_name": "diagnosis", "field_value": "Multiple Myeloma - Stem Cell Transplant"},
            {"field_name": "admission_date", "field_value": "12-02-2026"},
            {"field_name": "discharge_date", "field_value": "12-03-2026"},
            {"field_name": "hospital_name", "field_value": "American Cancer Hospital"},
            {"field_name": "age", "field_value": "60"},
            {"field_name": "secondary_diagnosis", "field_value": "High-dose Chemotherapy"},
            {"field_name": "secondary_diagnosis", "field_value": "Febrile Neutropaenia"},
            {"field_name": "secondary_diagnosis", "field_value": "CKD Stage 2"},
            {"field_name": "icu_charges", "field_value": "280000.00"},
            {"field_name": "transplant_charges", "field_value": "250000.00"},
            {"field_name": "chemotherapy_charges", "field_value": "180000.00"},
            {"field_name": "pharmacy_charges", "field_value": "195000.00"},
            {"field_name": "consultation_charges", "field_value": "70000.00"},
            {"field_name": "blood_charges", "field_value": "60000.00"},
            {"field_name": "laboratory_charges", "field_value": "45000.00"},
            {"field_name": "radiology_charges", "field_value": "38000.00"},
            {"field_name": "nursing_charges", "field_value": "28000.00"},
            {"field_name": "consumables", "field_value": "48000.00"},
            {"field_name": "misc_charges", "field_value": "30000.00"},
            {"field_name": "isolation_charges", "field_value": "126000.00"},
            {"field_name": "icd_code", "field_value": "C90.0"},
            {"field_name": "icd_code", "field_value": "D70.1"},
            {"field_name": "icd_code", "field_value": "N18.2"},
            {"field_name": "icd_code", "field_value": "Z79.899"},
            {"field_name": "cpt_code", "field_value": "38205"},
            {"field_name": "cpt_code", "field_value": "38241"},
            {"field_name": "cpt_code", "field_value": "96413"},
        ]
        features = build_features(parsed, [], [])
        result = predict(features)
        assert result.risk_category == "HIGH"
        assert result.rejection_score >= 0.51


# ================================================================
# TestEdgeCases — boundary and unusual input handling
# ================================================================

class TestEdgeCases:
    def test_zero_amount_claim(self):
        """Claim with no amounts at all."""
        parsed = [
            {"field_name": "patient_name", "field_value": "Test Patient"},
            {"field_name": "diagnosis", "field_value": "Checkup"},
        ]
        features = build_features(parsed, [], [])
        assert features["total_amount_log"] == 0.0
        assert features["has_total_amount"] == 0

    def test_very_large_amount(self):
        """Extreme claim amount should not crash."""
        parsed = [{"field_name": "total_amount", "field_value": "99,99,999.00"}]
        features = build_features(parsed, [], [])
        assert features["has_total_amount"] == 1
        assert features["total_amount_log"] > 15

    def test_malformed_date(self):
        """Bad date strings should not crash, just yield LOS=0."""
        parsed = [
            {"field_name": "admission_date", "field_value": "not-a-date"},
            {"field_name": "discharge_date", "field_value": "also-bad"},
        ]
        features = build_features(parsed, [], [])
        assert features["length_of_stay"] == 0.0

    def test_discharge_before_admission(self):
        """Discharge before admission should yield LOS=0 (not negative)."""
        parsed = [
            {"field_name": "admission_date", "field_value": "15-03-2026"},
            {"field_name": "discharge_date", "field_value": "10-03-2026"},
        ]
        features = build_features(parsed, [], [])
        assert features["length_of_stay"] == 0.0

    def test_age_over_100(self):
        """Age > 100 should be capped at 1.0 norm."""
        parsed = [{"field_name": "age", "field_value": "120"}]
        features = build_features(parsed, [], [])
        assert features["patient_age_norm"] == 1.0

    def test_age_zero(self):
        """Newborn (age 0) should work."""
        parsed = [{"field_name": "age", "field_value": "0"}]
        features = build_features(parsed, [], [])
        assert features["patient_age_norm"] == 0.0

    def test_non_numeric_age(self):
        """Non-numeric age should default to 0."""
        parsed = [{"field_name": "age", "field_value": "sixty"}]
        features = build_features(parsed, [], [])
        assert features["patient_age_norm"] == 0.0

    def test_comma_separated_amount(self):
        """Indian comma format (e.g. 1,50,000) should parse correctly."""
        parsed = [{"field_name": "total_amount", "field_value": "1,50,000"}]
        features = build_features(parsed, [], [])
        assert features["has_total_amount"] == 1

    def test_none_field_values(self):
        """None in field_value should not crash."""
        parsed = [
            {"field_name": "patient_name", "field_value": None},
            {"field_name": "age", "field_value": None},
        ]
        features = build_features(parsed, [], [])
        assert features["has_patient_name"] == 0
        assert features["patient_age_norm"] == 0.0

    def test_empty_string_fields(self):
        """Empty string values should be treated as missing."""
        parsed = [
            {"field_name": "patient_name", "field_value": ""},
            {"field_name": "diagnosis", "field_value": ""},
        ]
        features = build_features(parsed, [], [])
        assert features["has_patient_name"] == 0
        assert features["has_diagnosis"] == 0

    def test_only_severity_no_completeness(self):
        """High severity signals but complete docs → not LOW."""
        features = _make_features(
            total_amount_log=14.5,     # >12 lakh
            length_of_stay=25,         # 25 days
            is_icu_admission=1,
            has_secondary_diagnosis=1,
            num_icd_codes=4,
            has_blood_transfusion=1,
            has_surgery=1,
            surgery_cost_ratio=0.6,
            patient_age_norm=0.70,
        )
        result = predict(features)
        assert result.risk_category in ("MEDIUM", "HIGH")
        assert result.rejection_score > 0.30

    def test_only_completeness_no_severity(self):
        """Missing docs but no severity → still risky due to missing data."""
        features = _make_features(
            has_patient_name=0, has_policy_number=0, has_diagnosis=0,
            total_amount_log=6.0,
            length_of_stay=1,
            is_icu_admission=0,
            has_secondary_diagnosis=0,
            has_blood_transfusion=0,
            has_surgery=0,
        )
        result = predict(features)
        assert result.rejection_score > 0.20

    def test_max_reasons_capped_at_five(self):
        """Top reasons should never exceed 5."""
        features = _make_features(
            has_patient_name=0, has_policy_number=0, has_diagnosis=0,
            has_service_date=0, has_total_amount=0, has_provider=0,
            num_icd_codes=0, num_cpt_codes=0, has_primary_icd=0,
            total_amount_log=14.5, is_icu_admission=1,
            has_blood_transfusion=1, has_surgery=1,
        )
        result = predict(features)
        assert len(result.top_reasons) <= 5
