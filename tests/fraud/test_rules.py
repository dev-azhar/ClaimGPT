"""Tests for fraud rule engine + ML scorer + score blending."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "fraud"))
for _k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from services.fraud.app.ml import build_ml_features, score_anomaly
from services.fraud.app.rules import FraudContext, aggregate_rules_score, run_rules


def _make_ctx(**overrides) -> FraudContext:
    base = dict(
        claim_id="00000000-0000-0000-0000-000000000001",
        field_map={
            "patient_name": "John Doe",
            "policy_number": "POL-12345",
            "diagnosis": "Type 2 diabetes",
            "service_date": "2026-04-15",
            "total_amount": "75000",
            "sum_insured": "500000",
            "provider_name": "City Medical Center",
            "icu_charges": "10000",
            "surgery_charges": "20000",
            "pharmacy_charges": "5000",
            "room_charges": "20000",
            "consultation_charges": "5000",
            "investigation_charges": "10000",
            "nursing_charges": "5000",
        },
        codes=[
            {"code": "E11.9", "code_system": "ICD10", "is_primary": True},
            {"code": "99213", "code_system": "CPT", "is_primary": False},
        ],
        entities=[],
        rejection_score=0.15,
        history=[],
        duplicate_candidates=[],
        velocity_window_days=30,
        velocity_max_claims=5,
        provider_blacklist=set(),
    )
    base.update(overrides)
    return FraudContext(**base)


# ─────────────────────────────────────────────────────── Rules
class TestFraudRules:
    def test_clean_claim_no_high_severity_hits(self):
        ctx = _make_ctx()
        hits = run_rules(ctx)
        assert all(h.severity != "HIGH" for h in hits), [h.code for h in hits if h.severity == "HIGH"]

    def test_amount_exceeds_sum_insured(self):
        ctx = _make_ctx()
        ctx.field_map["total_amount"] = "1000000"   # 10 lakh on a 5 lakh policy
        ctx.field_map["sum_insured"] = "500000"
        hits = run_rules(ctx)
        codes = {h.code for h in hits}
        assert "R-BILL-01" in codes

    def test_round_number_billing(self):
        ctx = _make_ctx()
        ctx.field_map["total_amount"] = "250000"
        # disable the breakdown reconciliation noise so we focus on R-BILL-02
        for k in ("room_charges", "icu_charges", "surgery_charges", "ot_charges",
                  "pharmacy_charges", "investigation_charges",
                  "consultation_charges", "nursing_charges", "consumables_charges"):
            ctx.field_map.pop(k, None)
        hits = run_rules(ctx)
        assert "R-BILL-02" in {h.code for h in hits}

    def test_charge_breakdown_inconsistency(self):
        ctx = _make_ctx()
        ctx.field_map["total_amount"] = "200000"   # line items only sum to 75k
        hits = run_rules(ctx)
        assert "R-BILL-03" in {h.code for h in hits}

    def test_provider_blacklist(self):
        ctx = _make_ctx()
        ctx.provider_blacklist = {"city medical center"}
        hits = run_rules(ctx)
        assert "R-PROV-01" in {h.code for h in hits}

    def test_velocity_triggers(self):
        ctx = _make_ctx()
        now = datetime.now(timezone.utc)
        ctx.history = [
            {"claim_id": str(i), "created_at": (now - timedelta(days=i)).isoformat()}
            for i in range(1, 9)
        ]
        ctx.velocity_max_claims = 5
        hits = run_rules(ctx)
        assert "R-VEL-01" in {h.code for h in hits}

    def test_duplicate_amount_and_date(self):
        ctx = _make_ctx()
        ctx.duplicate_candidates = [{
            "claim_id": "abc",
            "total_amount": 75000.0,
            "service_date": "2026-04-15",
            "provider": "city medical center",
            "primary_icd": "E11.9",
        }]
        hits = run_rules(ctx)
        codes = {h.code for h in hits}
        assert "R-DUP-01" in codes

    def test_diagnosis_procedure_mismatch(self):
        ctx = _make_ctx()
        ctx.field_map["diagnosis"] = ""
        ctx.field_map["primary_diagnosis"] = ""
        ctx.codes = [
            {"code": "47600", "code_system": "CPT", "is_primary": False},  # cholecystectomy, no DX
        ]
        hits = run_rules(ctx)
        assert "R-CODE-02" in {h.code for h in hits}

    def test_unbundled_procedures(self):
        ctx = _make_ctx()
        ctx.codes = [
            {"code": f"9921{i % 10}", "code_system": "CPT", "is_primary": False}
            for i in range(12)
        ] + [{"code": "E11.9", "code_system": "ICD10", "is_primary": True}]
        hits = run_rules(ctx)
        assert "R-CODE-01" in {h.code for h in hits}

    def test_missing_identifiers(self):
        ctx = _make_ctx()
        ctx.field_map["policy_number"] = ""
        ctx.field_map["patient_id"] = ""
        ctx.field_map["member_id"] = ""
        hits = run_rules(ctx)
        assert "R-IDEN-01" in {h.code for h in hits}


# ─────────────────────────────────────────────────────── Aggregation
class TestRulesAggregation:
    def test_no_hits_zero_score(self):
        assert aggregate_rules_score([]) == 0.0

    def test_score_capped_at_one(self):
        ctx = _make_ctx()
        # Synthesize two HIGH-weight rules
        ctx.field_map["total_amount"] = "1000000"   # R-BILL-01
        ctx.field_map["sum_insured"] = "500000"
        ctx.duplicate_candidates = [{
            "claim_id": "x",
            "total_amount": 1_000_000.0,
            "service_date": "2026-04-15",
            "provider": "city medical center",
            "primary_icd": "E11.9",
        }]
        hits = run_rules(ctx)
        score = aggregate_rules_score(hits)
        assert 0.0 <= score <= 1.0
        assert score > 0.85   # multiple HIGH hits should push score very high


# ─────────────────────────────────────────────────────── ML scorer
class TestMlScorer:
    def test_clean_claim_low_anomaly(self):
        feats = build_ml_features(
            field_map={
                "total_amount": "30000",
                "sum_insured": "500000",
                "icu_charges": "0",
                "surgery_charges": "0",
                "pharmacy_charges": "5000",
                "length_of_stay": "3",
            },
            codes=[{"code": "E11.9", "code_system": "ICD10", "is_primary": True}],
            history_count_30d=0,
        )
        score, model_name = score_anomaly(feats)
        assert 0.0 <= score <= 1.0
        assert score < 0.5
        assert model_name

    def test_extreme_claim_high_anomaly(self):
        feats = build_ml_features(
            field_map={
                "total_amount": "900000",     # nearly entire policy
                "sum_insured": "1000000",
                "icu_charges": "700000",      # 78% of bill is ICU
                "surgery_charges": "150000",
                "pharmacy_charges": "30000",
                "length_of_stay": "2",        # 2-day stay → 4.5L/day
            },
            codes=[{"code": "I50.9", "code_system": "ICD10", "is_primary": True}],
            history_count_30d=8,
        )
        score, _ = score_anomaly(feats)
        assert score > 0.6
