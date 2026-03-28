"""
Payer adapter plugin system.

Each adapter translates a claim payload to the payer's expected format
and submits it. Add new adapters by subclassing PayerAdapter and
registering in ADAPTERS.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("submission.adapters")


class PayerAdapter(ABC):
    """Base class for payer submission adapters."""

    @abstractmethod
    def build_payload(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform internal claim data to the payer's schema."""
        ...

    @abstractmethod
    def submit(self, payload: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Send the payload to the payer.
        Returns (status, response_payload).
        """
        ...


class GenericAdapter(PayerAdapter):
    """
    Default adapter — builds a generic JSON payload and simulates submission.
    Replace with real HTTP calls to payer APIs, FHIR endpoints, etc.
    """

    def build_payload(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "claim_id": claim_data.get("claim_id"),
            "policy_id": claim_data.get("policy_id"),
            "patient_id": claim_data.get("patient_id"),
            "diagnosis_codes": claim_data.get("icd_codes", []),
            "procedure_codes": claim_data.get("cpt_codes", []),
            "parsed_fields": claim_data.get("parsed_fields", {}),
        }

    def submit(self, payload: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        logger.info("GenericAdapter: submitting claim %s", payload.get("claim_id"))
        return "SUBMITTED", {
            "ack": True,
            "reference": f"REF-{payload.get('claim_id', 'unknown')[:8]}",
            "message": "Claim accepted for processing",
        }


class FHIRAdapter(PayerAdapter):
    """
    HL7 FHIR R4 adapter — converts claim data to a FHIR Claim resource
    and POSTs to a FHIR-compliant payer endpoint.
    """

    FHIR_ENDPOINT = os.getenv("FHIR_ENDPOINT", "")
    FHIR_AUTH_TOKEN = os.getenv("FHIR_AUTH_TOKEN", "")

    def build_payload(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build a FHIR R4 Claim resource from internal data."""
        pf = claim_data.get("parsed_fields", {})
        icd_codes = claim_data.get("icd_codes", [])
        cpt_codes = claim_data.get("cpt_codes", [])

        # Diagnosis entries
        diagnoses: List[Dict[str, Any]] = []
        for i, code in enumerate(icd_codes, start=1):
            diagnoses.append({
                "sequence": i,
                "diagnosisCodeableConcept": {
                    "coding": [{
                        "system": "http://hl7.org/fhir/sid/icd-10-cm",
                        "code": code,
                    }]
                },
            })

        # Procedure / item entries
        items: List[Dict[str, Any]] = []
        for i, code in enumerate(cpt_codes, start=1):
            item: Dict[str, Any] = {
                "sequence": i,
                "productOrService": {
                    "coding": [{
                        "system": "http://www.ama-assn.org/go/cpt",
                        "code": code,
                    }]
                },
            }
            # Attach service date if available
            svc_date = pf.get("service_date")
            if svc_date:
                item["servicedDate"] = svc_date
            items.append(item)

        # If no items from CPT, add a placeholder item (FHIR requires ≥1 item)
        if not items:
            items.append({
                "sequence": 1,
                "productOrService": {
                    "coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": "99999"}]
                },
            })

        total_amount = pf.get("total_amount")

        resource: Dict[str, Any] = {
            "resourceType": "Claim",
            "status": "active",
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                    "code": "professional",
                }]
            },
            "use": "claim",
            "patient": {
                "reference": f"Patient/{claim_data.get('patient_id', 'unknown')}",
            },
            "created": pf.get("service_date", ""),
            "provider": {
                "reference": f"Organization/{pf.get('provider_name', 'unknown')}",
            },
            "priority": {
                "coding": [{"code": "normal"}]
            },
            "insurance": [{
                "sequence": 1,
                "focal": True,
                "coverage": {
                    "reference": f"Coverage/{claim_data.get('policy_id', 'unknown')}",
                },
            }],
            "diagnosis": diagnoses,
            "item": items,
        }

        if total_amount:
            try:
                resource["total"] = {
                    "value": float(total_amount),
                    "currency": "USD",
                }
            except (ValueError, TypeError):
                pass

        return resource

    def submit(self, payload: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """POST the FHIR Claim resource to the payer endpoint."""
        if not self.FHIR_ENDPOINT:
            logger.warning("FHIR_ENDPOINT not configured — simulating submission")
            return "SUBMITTED", {
                "ack": True,
                "message": "FHIR endpoint not configured; payload built successfully",
                "resourceType": "Claim",
            }

        headers = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if self.FHIR_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {self.FHIR_AUTH_TOKEN}"

        try:
            resp = httpx.post(
                f"{self.FHIR_ENDPOINT}/Claim",
                json=payload,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            return "SUBMITTED", resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("FHIR submission failed: %s %s", e.response.status_code, e.response.text[:500])
            return "FAILED", {
                "error": str(e.response.status_code),
                "detail": e.response.text[:1000],
            }
        except httpx.RequestError as e:
            logger.error("FHIR request error: %s", e)
            return "FAILED", {"error": str(e)}


class X12Adapter(PayerAdapter):
    """
    X12 837P EDI adapter — converts claim data to X12 837 Professional format.
    Used for traditional clearinghouse submissions.
    """

    X12_ENDPOINT = os.getenv("X12_ENDPOINT", "")
    X12_SENDER_ID = os.getenv("X12_SENDER_ID", "CLAIMGPT")
    X12_RECEIVER_ID = os.getenv("X12_RECEIVER_ID", "")

    def build_payload(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build an X12-compatible payload structure."""
        pf = claim_data.get("parsed_fields", {})
        return {
            "format": "X12_837P",
            "sender_id": self.X12_SENDER_ID,
            "receiver_id": self.X12_RECEIVER_ID,
            "claim_id": claim_data.get("claim_id"),
            "patient": {
                "id": claim_data.get("patient_id"),
                "name": pf.get("patient_name", ""),
                "dob": pf.get("date_of_birth", ""),
            },
            "subscriber": {
                "policy_number": claim_data.get("policy_id"),
            },
            "provider": {
                "name": pf.get("provider_name", ""),
                "npi": pf.get("provider_npi", ""),
            },
            "diagnoses": [
                {"code": c, "system": "ICD10"} for c in claim_data.get("icd_codes", [])
            ],
            "procedures": [
                {"code": c, "system": "CPT"} for c in claim_data.get("cpt_codes", [])
            ],
            "service_date": pf.get("service_date", ""),
            "total_amount": pf.get("total_amount", ""),
        }

    def submit(self, payload: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Submit X12 payload to clearinghouse endpoint."""
        if not self.X12_ENDPOINT:
            logger.warning("X12_ENDPOINT not configured — simulating submission")
            return "SUBMITTED", {
                "ack": True,
                "message": "X12 endpoint not configured; payload built successfully",
                "format": "X12_837P",
            }

        try:
            resp = httpx.post(
                self.X12_ENDPOINT,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return "SUBMITTED", resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("X12 submission failed: %s", e.response.status_code)
            return "FAILED", {
                "error": str(e.response.status_code),
                "detail": e.response.text[:1000],
            }
        except httpx.RequestError as e:
            logger.error("X12 request error: %s", e)
            return "FAILED", {"error": str(e)}


# ------------------------------------------------------------------ registry
ADAPTERS: Dict[str, type[PayerAdapter]] = {
    "generic": GenericAdapter,
    "fhir": FHIRAdapter,
    "x12": X12Adapter,
}


def get_adapter(payer: str) -> PayerAdapter:
    cls = ADAPTERS.get(payer.lower())
    if not cls:
        logger.warning("No adapter for payer '%s', falling back to generic", payer)
        cls = GenericAdapter
    return cls()
