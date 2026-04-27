"""Tests for the submission payer adapters."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "submission"))

from app.adapters import (
    FHIRAdapter,
    GenericAdapter,
    X12Adapter,
    get_adapter,
)


def _sample_claim_data():
    return {
        "claim_id": "a0000000-0000-0000-0000-000000000001",
        "policy_id": "POL-12345",
        "patient_id": "PAT-67890",
        "icd_codes": ["E11.9", "I10"],
        "cpt_codes": ["99213"],
        "parsed_fields": {
            "patient_name": "John Doe",
            "service_date": "2026-01-15",
            "total_amount": "1250.00",
            "provider_name": "City Medical",
        },
    }


class TestGenericAdapter:
    def test_build_payload(self):
        adapter = GenericAdapter()
        payload = adapter.build_payload(_sample_claim_data())
        assert payload["claim_id"] == "a0000000-0000-0000-0000-000000000001"
        assert "E11.9" in payload["diagnosis_codes"]
        assert "99213" in payload["procedure_codes"]

    def test_submit_returns_submitted(self):
        adapter = GenericAdapter()
        payload = adapter.build_payload(_sample_claim_data())
        status, response = adapter.submit(payload)
        assert status == "SUBMITTED"
        assert response["ack"] is True


class TestFHIRAdapter:
    def test_build_fhir_resource(self):
        adapter = FHIRAdapter()
        resource = adapter.build_payload(_sample_claim_data())
        assert resource["resourceType"] == "Claim"
        assert resource["status"] == "active"
        assert len(resource["diagnosis"]) == 2
        assert resource["diagnosis"][0]["diagnosisCodeableConcept"]["coding"][0]["code"] == "E11.9"
        assert len(resource["item"]) >= 1
        assert resource["total"]["value"] == 1250.0

    def test_fhir_no_items_adds_placeholder(self):
        data = _sample_claim_data()
        data["cpt_codes"] = []
        adapter = FHIRAdapter()
        resource = adapter.build_payload(data)
        assert len(resource["item"]) == 1
        assert resource["item"][0]["productOrService"]["coding"][0]["code"] == "99999"

    def test_fhir_submit_without_endpoint_simulates(self):
        adapter = FHIRAdapter()
        adapter.FHIR_ENDPOINT = ""
        payload = adapter.build_payload(_sample_claim_data())
        status, response = adapter.submit(payload)
        assert status == "SUBMITTED"
        assert "FHIR endpoint not configured" in response["message"]


class TestX12Adapter:
    def test_build_x12_payload(self):
        adapter = X12Adapter()
        payload = adapter.build_payload(_sample_claim_data())
        assert payload["format"] == "X12_837P"
        assert payload["patient"]["id"] == "PAT-67890"
        assert len(payload["diagnoses"]) == 2
        assert payload["diagnoses"][0]["code"] == "E11.9"

    def test_x12_submit_without_endpoint_simulates(self):
        adapter = X12Adapter()
        adapter.X12_ENDPOINT = ""
        payload = adapter.build_payload(_sample_claim_data())
        status, response = adapter.submit(payload)
        assert status == "SUBMITTED"


class TestAdapterRegistry:
    def test_get_generic_adapter(self):
        adapter = get_adapter("generic")
        assert isinstance(adapter, GenericAdapter)

    def test_get_fhir_adapter(self):
        adapter = get_adapter("fhir")
        assert isinstance(adapter, FHIRAdapter)

    def test_get_x12_adapter(self):
        adapter = get_adapter("x12")
        assert isinstance(adapter, X12Adapter)

    def test_unknown_falls_back_to_generic(self):
        adapter = get_adapter("nonexistent_payer")
        assert isinstance(adapter, GenericAdapter)

    def test_case_insensitive(self):
        adapter = get_adapter("FHIR")
        assert isinstance(adapter, FHIRAdapter)
