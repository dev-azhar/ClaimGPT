"""Tests for the predictor feature engineering + scoring engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "predictor"))

from app.engine import build_features, predict


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
        assert features["num_icd_codes"] == 1
        assert features["num_cpt_codes"] == 1
        assert features["has_primary_icd"] == 1
        assert features["num_parsed_fields"] == 6

    def test_empty_claim_features(self):
        features = build_features([], [], [])
        assert features["has_patient_name"] == 0
        assert features["num_parsed_fields"] == 0
        assert features["num_icd_codes"] == 0


class TestPredict:
    def test_good_claim_low_score(self):
        features = {
            "has_patient_name": 1,
            "has_policy_number": 1,
            "has_diagnosis": 1,
            "has_service_date": 1,
            "has_total_amount": 1,
            "has_provider": 1,
            "num_parsed_fields": 6,
            "num_entities": 2,
            "num_icd_codes": 1,
            "num_cpt_codes": 1,
            "has_primary_icd": 1,
            "num_diagnosis_types": 1,
            "total_amount_log": 6.2,
        }
        result = predict(features)
        assert result.rejection_score < 0.3
        assert result.model_name is not None

    def test_bad_claim_high_score(self):
        features = {
            "has_patient_name": 0,
            "has_policy_number": 0,
            "has_diagnosis": 0,
            "has_service_date": 0,
            "has_total_amount": 0,
            "has_provider": 0,
            "num_parsed_fields": 1,
            "num_entities": 0,
            "num_icd_codes": 0,
            "num_cpt_codes": 0,
            "has_primary_icd": 0,
            "num_diagnosis_types": 0,
            "total_amount_log": 0.0,
        }
        result = predict(features)
        assert result.rejection_score > 0.5
        assert len(result.top_reasons) > 0

    def test_score_capped_at_one(self):
        features = {
            "has_patient_name": 0,
            "has_policy_number": 0,
            "has_diagnosis": 0,
            "has_service_date": 0,
            "has_total_amount": 0,
            "has_provider": 0,
            "num_parsed_fields": 0,
            "num_entities": 0,
            "num_icd_codes": 0,
            "num_cpt_codes": 0,
            "has_primary_icd": 0,
            "num_diagnosis_types": 0,
            "total_amount_log": 0.0,
        }
        result = predict(features)
        assert result.rejection_score <= 1.0

    def test_reasons_sorted_by_weight(self):
        features = {
            "has_patient_name": 0,
            "has_policy_number": 0,
            "has_diagnosis": 1,
            "has_service_date": 1,
            "has_total_amount": 1,
            "has_provider": 1,
            "num_parsed_fields": 5,
            "num_entities": 1,
            "num_icd_codes": 1,
            "num_cpt_codes": 1,
            "has_primary_icd": 1,
            "num_diagnosis_types": 1,
            "total_amount_log": 4.6,
        }
        result = predict(features)
        if len(result.top_reasons) > 1:
            weights = [r["weight"] for r in result.top_reasons]
            assert weights == sorted(weights, reverse=True)
