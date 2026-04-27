"""Tests for the validator rules engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "validator"))

from app.rules import run_rules


def _make_ctx(**overrides):
    """Build a default validation context with overrides."""
    ctx = {
        "field_map": {
            "patient_name": "John Doe",
            "policy_number": "POL-12345",
            "diagnosis": "Type 2 diabetes",
            "service_date": "2026-01-15",
            "total_amount": "1250.00",
            "provider_name": "City Medical Center",
        },
        "codes": [
            {"code": "E11.9", "code_system": "ICD10", "is_primary": True},
            {"code": "99213", "code_system": "CPT", "is_primary": False},
        ],
        "rejection_score": 0.15,
    }
    ctx.update(overrides)
    return ctx


class TestValidationRules:
    def test_all_pass_complete_claim(self):
        ctx = _make_ctx()
        results = run_rules(ctx)
        errors = [r for r in results if not r.passed and r.severity == "ERROR"]
        assert len(errors) == 0

    def test_missing_patient_name_fails(self):
        ctx = _make_ctx()
        ctx["field_map"]["patient_name"] = ""
        results = run_rules(ctx)
        r001 = next(r for r in results if r.rule_id == "R001")
        assert not r001.passed
        assert r001.severity == "ERROR"

    def test_missing_policy_number_fails(self):
        ctx = _make_ctx()
        ctx["field_map"]["policy_number"] = ""
        results = run_rules(ctx)
        r002 = next(r for r in results if r.rule_id == "R002")
        assert not r002.passed

    def test_missing_diagnosis_fails(self):
        ctx = _make_ctx()
        ctx["field_map"]["diagnosis"] = ""
        results = run_rules(ctx)
        r003 = next(r for r in results if r.rule_id == "R003")
        assert not r003.passed

    def test_no_icd_codes_fails(self):
        ctx = _make_ctx(codes=[{"code": "99213", "code_system": "CPT", "is_primary": False}])
        results = run_rules(ctx)
        r004 = next(r for r in results if r.rule_id == "R004")
        assert not r004.passed

    def test_missing_service_date_fails(self):
        ctx = _make_ctx()
        ctx["field_map"]["service_date"] = None
        results = run_rules(ctx)
        r005 = next(r for r in results if r.rule_id == "R005")
        assert not r005.passed

    def test_missing_total_warns(self):
        ctx = _make_ctx()
        ctx["field_map"]["total_amount"] = ""
        results = run_rules(ctx)
        r006 = next(r for r in results if r.rule_id == "R006")
        assert not r006.passed
        assert r006.severity == "WARN"

    def test_high_rejection_score_warns(self):
        ctx = _make_ctx(rejection_score=0.75)
        results = run_rules(ctx)
        r008 = next(r for r in results if r.rule_id == "R008")
        assert not r008.passed
        assert r008.severity == "WARN"

    def test_low_rejection_score_passes(self):
        ctx = _make_ctx(rejection_score=0.10)
        results = run_rules(ctx)
        r008 = next(r for r in results if r.rule_id == "R008")
        assert r008.passed

    def test_no_prediction_skips_score(self):
        ctx = _make_ctx(rejection_score=None)
        results = run_rules(ctx)
        r008 = next(r for r in results if r.rule_id == "R008")
        assert r008.passed  # No prediction → passes

    def test_total_rules_count(self):
        ctx = _make_ctx()
        results = run_rules(ctx)
        assert len(results) == 10  # R001-R010
