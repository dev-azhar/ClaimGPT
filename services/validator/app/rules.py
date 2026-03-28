"""
Rule engine for claim validation.

Each rule is a callable that receives a context dict and returns
(passed: bool, severity: str, message: str).
Rules are registered in RULES and executed sequentially.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("validator.rules")


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    passed: bool
    severity: str   # INFO / WARN / ERROR
    message: str


RuleFn = Callable[[Dict[str, Any]], Tuple[bool, str, str]]


def _field_present(field_map: Dict[str, Any], *keys: str) -> bool:
    """Check if any of the given field keys has a truthy value."""
    return any(bool(field_map.get(k)) for k in keys)


def _rule_has_patient_name(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "patient_name", "member_name", "insured_name", "patient")
    return ok, ("PASS" if ok else "ERROR"), ("Patient name found" if ok else "Patient name is required")


def _rule_has_policy_number(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "policy_number", "policy_id", "policy_no", "insurance_id", "member_id")
    return ok, ("PASS" if ok else "ERROR"), ("Policy number found" if ok else "Policy number is required")


def _rule_has_diagnosis(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "diagnosis", "primary_diagnosis", "chief_complaint", "clinical_diagnosis")
    return ok, ("PASS" if ok else "ERROR"), ("Diagnosis found" if ok else "At least one diagnosis is required")


def _rule_has_icd_code(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c["code_system"] == "ICD10" for c in ctx["codes"])
    return ok, ("PASS" if ok else "ERROR"), ("ICD-10 code found" if ok else "At least one ICD-10 code is required")


def _rule_has_service_date(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "service_date", "admission_date", "date_of_service", "treatment_date", "date_of_admission")
    return ok, ("PASS" if ok else "ERROR"), ("Date of service found" if ok else "Date of service is required")


def _rule_has_total_amount(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "total_amount", "amount", "billed_amount", "net_amount", "grand_total")
    return ok, ("PASS" if ok else "WARN"), ("Total amount found" if ok else "Total amount is missing — may delay processing")


def _rule_has_provider(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = _field_present(ctx["field_map"], "provider_name", "doctor_name", "hospital_name", "hospital", "rendering_provider", "treating_doctor", "surgeon")
    return ok, ("PASS" if ok else "WARN"), ("Provider name found" if ok else "Provider name is missing")


def _rule_low_rejection_score(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    score = ctx.get("rejection_score")
    if score is None:
        return True, "PASS", "No prediction available — skipping score check"
    ok = score < 0.5
    return ok, ("PASS" if ok else "WARN"), (
        f"High rejection risk score: {score:.2f}" if not ok
        else f"Rejection risk score acceptable: {score:.2f}"
    )


def _rule_has_cpt_code(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c["code_system"] == "CPT" for c in ctx["codes"])
    return ok, ("PASS" if ok else "WARN"), ("CPT procedure code found" if ok else "No CPT procedure code found")


def _rule_primary_icd_designated(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c.get("is_primary") and c["code_system"] == "ICD10" for c in ctx["codes"])
    return ok, ("PASS" if ok else "WARN"), ("Primary ICD-10 code designated" if ok else "No primary ICD-10 code designated")


# ------------------------------------------------------------------ registry
RULES: List[Tuple[str, str, RuleFn]] = [
    ("R001", "Patient name present",      _rule_has_patient_name),
    ("R002", "Policy number present",     _rule_has_policy_number),
    ("R003", "Diagnosis present",         _rule_has_diagnosis),
    ("R004", "ICD-10 code present",       _rule_has_icd_code),
    ("R005", "Date of service present",   _rule_has_service_date),
    ("R006", "Total amount present",      _rule_has_total_amount),
    ("R007", "Provider name present",     _rule_has_provider),
    ("R008", "Rejection score check",     _rule_low_rejection_score),
    ("R009", "CPT code present",          _rule_has_cpt_code),
    ("R010", "Primary ICD designated",    _rule_primary_icd_designated),
]


def run_rules(ctx: Dict[str, Any]) -> List[RuleResult]:
    """Execute all registered validation rules against a claim context."""
    results: List[RuleResult] = []
    for rule_id, rule_name, fn in RULES:
        try:
            passed, severity, message = fn(ctx)
        except Exception:
            logger.exception("Rule %s failed with exception", rule_id)
            passed, severity, message = False, "ERROR", f"Rule {rule_id} raised an exception"
        results.append(RuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            passed=passed,
            severity=severity,
            message=message,
        ))
    return results
