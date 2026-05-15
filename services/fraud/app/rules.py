"""
Rules-based fraud detectors.

Each rule receives a `FraudContext` and returns a list of `RuleHit`
(zero or more). The rules layer score is the weighted sum of fired
hits, capped at 1.0.

Rule code convention: R-<category>-<seq>
  DUP  duplicate / repeat claims
  BILL billing & financial anomalies
  PROV provider blacklist / risk
  VEL  claim velocity / frequency
  CODE coding inconsistencies
  IDEN identity / PII anomalies
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("fraud.rules")


@dataclass
class RuleHit:
    code: str
    name: str
    severity: str   # INFO / WARN / HIGH
    weight: float   # contribution to rules_score (0..1)
    message: str
    evidence: dict[str, Any] | None = None


@dataclass
class FraudContext:
    """All data a fraud rule may need. Built by `engine.build_context`."""

    claim_id: str
    field_map: dict[str, Any]
    codes: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    rejection_score: float | None = None

    # Historical lookback (other claims for same patient/policy/provider)
    history: list[dict[str, Any]] = field(default_factory=list)
    duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)

    # Configurable knobs (sourced from settings)
    velocity_window_days: int = 30
    velocity_max_claims: int = 5

    # Provider blacklist (lowercased names / IDs)
    provider_blacklist: set[str] = field(default_factory=set)


RuleFn = Callable[[FraudContext], list[RuleHit]]


# ─────────────────────────────────────────────────────── helpers
def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _amount(field_map: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = field_map.get(k)
        if v in (None, ""):
            continue
        try:
            return float(str(v).replace(",", "").replace("₹", "").replace("$", "").strip())
        except (ValueError, TypeError):
            continue
    return None


def _date(field_map: dict[str, Any], *keys: str) -> datetime | None:
    for k in keys:
        v = field_map.get(k)
        if not v:
            continue
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(v).strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ─────────────────────────────────────────────────────── DUP rules
def _rule_duplicate_amount_and_date(ctx: FraudContext) -> list[RuleHit]:
    """Same patient + same service date + same total amount as a prior claim."""
    if not ctx.duplicate_candidates:
        return []
    amount = _amount(ctx.field_map, "total_amount", "amount", "billed_amount", "grand_total")
    service_date = _date(ctx.field_map, "service_date", "admission_date", "date_of_service")

    if amount is None or service_date is None:
        return []

    matches = []
    for prior in ctx.duplicate_candidates:
        prior_amount = prior.get("total_amount")
        prior_date = prior.get("service_date")
        if prior_amount is None or prior_date is None:
            continue
        try:
            same_amount = abs(float(prior_amount) - amount) < 0.01
        except (ValueError, TypeError):
            continue
        if same_amount and prior_date == service_date.date().isoformat():
            matches.append(prior.get("claim_id"))

    if not matches:
        return []
    return [RuleHit(
        code="R-DUP-01",
        name="Exact-amount duplicate on same service date",
        severity="HIGH",
        weight=0.9,
        message=f"Found {len(matches)} prior claim(s) with same amount and service date",
        evidence={"matched_claims": matches[:5], "amount": amount, "service_date": service_date.date().isoformat()},
    )]


def _rule_near_duplicate_codes(ctx: FraudContext) -> list[RuleHit]:
    """Same primary ICD-10 + same provider + same week as a prior claim."""
    if not ctx.duplicate_candidates:
        return []
    primary_icd = next(
        (c["code"] for c in ctx.codes if c.get("is_primary") and c.get("code_system") == "ICD10"),
        None,
    )
    provider = _norm(
        ctx.field_map.get("provider_name")
        or ctx.field_map.get("hospital_name")
        or ctx.field_map.get("doctor_name")
    )
    service_date = _date(ctx.field_map, "service_date", "admission_date", "date_of_service")

    if not primary_icd or not provider or not service_date:
        return []

    matches = []
    for prior in ctx.duplicate_candidates:
        if _norm(prior.get("provider")) != provider:
            continue
        if prior.get("primary_icd") != primary_icd:
            continue
        prior_date = prior.get("service_date")
        if not prior_date:
            continue
        try:
            d = datetime.fromisoformat(prior_date).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if abs((service_date - d).days) <= 7:
            matches.append(prior.get("claim_id"))

    if not matches:
        return []
    return [RuleHit(
        code="R-DUP-02",
        name="Near-duplicate: same provider + ICD within 7 days",
        severity="WARN",
        weight=0.55,
        message=f"{len(matches)} similar claim(s) within a 7-day window",
        evidence={"matched_claims": matches[:5], "icd": primary_icd, "provider": provider},
    )]


# ─────────────────────────────────────────────────────── BILL rules
def _rule_amount_exceeds_sum_insured(ctx: FraudContext) -> list[RuleHit]:
    amount = _amount(ctx.field_map, "total_amount", "amount", "billed_amount", "grand_total")
    sum_insured = _amount(ctx.field_map, "sum_insured", "sum_assured", "policy_limit")
    if amount is None or sum_insured is None or sum_insured <= 0:
        return []
    if amount <= sum_insured:
        return []
    return [RuleHit(
        code="R-BILL-01",
        name="Billed amount exceeds policy sum insured",
        severity="HIGH",
        weight=0.75,
        message=f"Billed {amount:.2f} > sum insured {sum_insured:.2f}",
        evidence={"amount": amount, "sum_insured": sum_insured},
    )]


def _rule_round_number_billing(ctx: FraudContext) -> list[RuleHit]:
    """Frequent suspicious indicator: large bills ending in many zeros."""
    amount = _amount(ctx.field_map, "total_amount", "amount", "billed_amount", "grand_total")
    if amount is None or amount < 50_000:
        return []
    # All trailing zeros after the leading digits (e.g. 250000, 100000, 500000)
    if amount == int(amount) and int(amount) % 10_000 == 0:
        return [RuleHit(
            code="R-BILL-02",
            name="Suspiciously round large amount",
            severity="WARN",
            weight=0.25,
            message=f"Amount {amount:.0f} is an exact multiple of 10,000 — common in fabricated bills",
            evidence={"amount": amount},
        )]
    return []


def _rule_charge_breakdown_inconsistency(ctx: FraudContext) -> list[RuleHit]:
    """Sum of itemized charges doesn't match grand total (>10% drift)."""
    grand_total = _amount(ctx.field_map, "total_amount", "grand_total", "net_amount")
    if grand_total is None or grand_total <= 0:
        return []
    components = [
        _amount(ctx.field_map, k) or 0.0
        for k in ("room_charges", "icu_charges", "surgery_charges", "ot_charges",
                  "pharmacy_charges", "investigation_charges", "consultation_charges",
                  "nursing_charges", "consumables_charges")
    ]
    line_sum = sum(components)
    if line_sum <= 0:
        return []
    drift = abs(line_sum - grand_total) / grand_total
    if drift < 0.10:
        return []
    return [RuleHit(
        code="R-BILL-03",
        name="Itemized charges don't reconcile with grand total",
        severity="HIGH",
        weight=0.65,
        message=f"Line-item sum {line_sum:.2f} drifts {drift*100:.1f}% from grand total {grand_total:.2f}",
        evidence={"line_sum": line_sum, "grand_total": grand_total, "drift_pct": round(drift * 100, 2)},
    )]


# ─────────────────────────────────────────────────────── PROV rules
def _rule_provider_blacklist(ctx: FraudContext) -> list[RuleHit]:
    if not ctx.provider_blacklist:
        return []
    candidates = [
        _norm(ctx.field_map.get(k))
        for k in ("provider_name", "hospital_name", "doctor_name", "treating_doctor", "surgeon")
    ]
    hits = [c for c in candidates if c and c in ctx.provider_blacklist]
    if not hits:
        return []
    return [RuleHit(
        code="R-PROV-01",
        name="Provider on internal blacklist",
        severity="HIGH",
        weight=0.95,
        message=f"Provider matches blacklist entry: {hits[0]}",
        evidence={"matched": hits[0]},
    )]


# ─────────────────────────────────────────────────────── VEL rules
def _rule_claim_velocity(ctx: FraudContext) -> list[RuleHit]:
    """Too many claims for the same patient/policy in the rolling window."""
    if not ctx.history:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=ctx.velocity_window_days)
    recent = 0
    for h in ctx.history:
        ts = h.get("created_at")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= cutoff:
            recent += 1
    if recent <= ctx.velocity_max_claims:
        return []
    excess = recent - ctx.velocity_max_claims
    weight = min(0.8, 0.4 + 0.1 * excess)
    return [RuleHit(
        code="R-VEL-01",
        name="High claim velocity for patient/policy",
        severity="HIGH" if excess >= 3 else "WARN",
        weight=weight,
        message=f"{recent} claims in last {ctx.velocity_window_days} days (threshold {ctx.velocity_max_claims})",
        evidence={"window_days": ctx.velocity_window_days, "recent_count": recent},
    )]


# ─────────────────────────────────────────────────────── CODE rules
def _rule_unbundled_procedures(ctx: FraudContext) -> list[RuleHit]:
    """More than 8 distinct CPT codes on a single claim is a classic
    upcoding/unbundling indicator. Tunable in future."""
    cpt_codes = {c["code"] for c in ctx.codes if c.get("code_system") == "CPT"}
    if len(cpt_codes) <= 8:
        return []
    return [RuleHit(
        code="R-CODE-01",
        name="Excessive distinct CPT codes (possible unbundling)",
        severity="WARN",
        weight=0.35,
        message=f"{len(cpt_codes)} distinct CPT codes — review for bundling",
        evidence={"cpt_count": len(cpt_codes)},
    )]


def _rule_diagnosis_procedure_mismatch(ctx: FraudContext) -> list[RuleHit]:
    """Procedures present but no diagnosis at all — billing without
    clinical justification."""
    has_dx = any(c.get("code_system") == "ICD10" for c in ctx.codes) or bool(
        ctx.field_map.get("diagnosis") or ctx.field_map.get("primary_diagnosis")
    )
    has_proc = any(c.get("code_system") == "CPT" for c in ctx.codes) or bool(
        _amount(ctx.field_map, "surgery_charges", "ot_charges")
    )
    if has_dx or not has_proc:
        return []
    return [RuleHit(
        code="R-CODE-02",
        name="Procedures billed without supporting diagnosis",
        severity="HIGH",
        weight=0.6,
        message="Procedure/surgery charges present but no diagnosis or ICD-10 code recorded",
    )]


# ─────────────────────────────────────────────────────── IDEN rules
def _rule_missing_identifiers(ctx: FraudContext) -> list[RuleHit]:
    """Claim missing both policy id and patient id is a soft fraud signal."""
    has_policy = bool(
        ctx.field_map.get("policy_number") or ctx.field_map.get("policy_id")
    )
    has_patient_id = bool(
        ctx.field_map.get("patient_id") or ctx.field_map.get("member_id")
    )
    if has_policy or has_patient_id:
        return []
    return [RuleHit(
        code="R-IDEN-01",
        name="Both policy and patient identifiers missing",
        severity="WARN",
        weight=0.3,
        message="Cannot tie claim to a verifiable policy or member",
    )]


# ─────────────────────────────────────────────────────── registry
RULES: list[RuleFn] = [
    _rule_duplicate_amount_and_date,
    _rule_near_duplicate_codes,
    _rule_amount_exceeds_sum_insured,
    _rule_round_number_billing,
    _rule_charge_breakdown_inconsistency,
    _rule_provider_blacklist,
    _rule_claim_velocity,
    _rule_unbundled_procedures,
    _rule_diagnosis_procedure_mismatch,
    _rule_missing_identifiers,
]


def run_rules(ctx: FraudContext) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for fn in RULES:
        try:
            hits.extend(fn(ctx) or [])
        except Exception:
            logger.exception("Fraud rule %s raised", fn.__name__)
    return hits


def aggregate_rules_score(hits: list[RuleHit]) -> float:
    """
    Combine independent rule weights using probabilistic OR
    (1 − Π(1 − w_i)). Caps naturally at 1.0 and avoids over-counting
    when several mid-weight rules fire together.
    """
    if not hits:
        return 0.0
    prod = 1.0
    for h in hits:
        w = max(0.0, min(1.0, h.weight))
        prod *= (1.0 - w)
    return round(1.0 - prod, 4)
