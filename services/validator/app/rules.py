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


def _rule_has_patient_name(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("patient_name"))
    return ok, "ERROR", "Patient name is required"


def _rule_has_policy_number(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("policy_number"))
    return ok, "ERROR", "Policy number is required"


def _rule_has_diagnosis(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("diagnosis"))
    return ok, "ERROR", "At least one diagnosis is required"


def _rule_has_icd_code(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c["code_system"] == "ICD10" for c in ctx["codes"])
    return ok, "ERROR", "At least one ICD-10 code is required"


def _rule_has_service_date(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("service_date"))
    return ok, "ERROR", "Date of service is required"


def _rule_has_total_amount(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("total_amount"))
    return ok, "WARN", "Total amount is missing — may delay processing"


def _rule_has_provider(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = bool(ctx["field_map"].get("provider_name"))
    return ok, "WARN", "Provider name is missing"


def _rule_low_rejection_score(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    score = ctx.get("rejection_score")
    if score is None:
        return True, "INFO", "No prediction available — skipping score check"
    ok = score < 0.5
    return ok, "WARN" if not ok else "INFO", (
        f"High rejection risk score: {score:.2f}" if not ok
        else f"Rejection risk score acceptable: {score:.2f}"
    )


def _rule_has_cpt_code(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c["code_system"] == "CPT" for c in ctx["codes"])
    return ok, "WARN", "No CPT procedure code found"


def _rule_primary_icd_designated(ctx: Dict[str, Any]) -> Tuple[bool, str, str]:
    ok = any(c.get("is_primary") and c["code_system"] == "ICD10" for c in ctx["codes"])
    return ok, "WARN", "No primary ICD-10 code designated"


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
