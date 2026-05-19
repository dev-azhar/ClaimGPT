from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .adapters import get_adapter
from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import (
    Claim,
    ClaimFieldFeedback,
    Document,
    DocValidation,
    MedicalCode,
    OcrResult,
    ParsedField,
    Prediction,
    ScanAnalysis,
    Submission,
    TpaProvider,
)
from libs.auth.middleware import get_current_user
from libs.auth.models import TokenPayload
from .schemas import SubmissionDetailOut, SubmissionOut, SubmitRequest
from .tpa_pdf import _generate_brain_insights, _generate_reimbursement_brain, generate_tpa_pdf
from .irda_pdf import generate_irda_pdf
try:
    from .irda_pdf_modern import generate_irda_pdf_modern  # type: ignore
except Exception as _exc:  # pragma: no cover - WeasyPrint optional at import time
    generate_irda_pdf_modern = None  # type: ignore
    logging.getLogger("submission").warning("Modern IRDA renderer unavailable: %s", _exc)

# Import rules engine for live re-validation in preview.
# In isolated service containers, this package may be unavailable.
try:
    from services.validator.app.rules import run_rules as _run_validation_rules
except Exception:  # pragma: no cover - environment-specific fallback
    _run_validation_rules = None

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("submission")

app = FastAPI(title="ClaimGPT Submission Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ observability
try:
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from libs.observability.metrics import PrometheusMiddleware, init_metrics, metrics_endpoint
    from libs.observability.tracing import init_tracing, instrument_fastapi
    init_tracing("submission")
    init_metrics("submission")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


@app.on_event("shutdown")
def _shutdown():
    engine.dispose()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")


def _sort_icd_codes(codes: list[MedicalCode]) -> list[MedicalCode]:
    icd_codes = [c for c in codes if c.code_system == "ICD10"]
    return sorted(
        icd_codes,
        key=lambda c: (
            1 if c.is_primary else 0,
            float(c.confidence or 0.0),
            float(c.estimated_cost or 0.0),
        ),
        reverse=True,
    )

def _pick_best_field_value(field_name: str, values: list[tuple[str, str]]) -> str:
    """Pick the best value for a parsed field.

    Each element in *values* is a ``(raw_value, model_version)`` tuple so
    that source-aware prioritisation can be applied.  For money fields the
    expense-table extraction is authoritative (it sums line items correctly),
    so if an expense-table value exists we prefer it over heuristic/regex
    values.  Otherwise we fall back to the previous "pick MAX" behaviour.
    """
    clean: list[tuple[str, str]] = [
        (v, mv) for v, mv in values if isinstance(v, str) and v.strip()
    ]
    if not clean:
        return ""

    money_fields = {
        "total_amount", "room_charges", "consultation_charges", "pharmacy_charges",
        "investigation_charges", "surgery_charges", "surgeon_fees", "anaesthesia_charges",
        "ot_charges", "consumables", "nursing_charges", "icu_charges",
        "ambulance_charges", "misc_charges", "other_charges",
        "laboratory_charges", "radiology_charges", "physiotherapy_charges",
        "blood_charges", "isolation_charges", "transplant_charges", "chemotherapy_charges",
    }

    if field_name in money_fields:
        PRIORITY_ORDER = [
            "parser_v2",
            "expense-table-v4",
            "expense-table-geo-v1",
            "expense-table-v2",
            "heuristic-v2",
        ]
        
        def get_priority(mv: str) -> int:
            for i, p in enumerate(PRIORITY_ORDER):
                if (mv or "").startswith(p):
                    return i
            return len(PRIORITY_ORDER)

        # Group valid numeric candidates by model priority
        grouped_candidates = {}
        for v, mv in clean:
            m = re.search(r"\d[\d,]*\.?\d*", v)
            if not m:
                continue
            try:
                num = float(m.group(0).replace(",", ""))
            except ValueError:
                continue
                
            priority = get_priority(mv)
            if priority not in grouped_candidates:
                grouped_candidates[priority] = []
            grouped_candidates[priority].append(num)

        if grouped_candidates:
            # Get the highest priority group (lowest index)
            best_priority = min(grouped_candidates.keys())
            best_group = grouped_candidates[best_priority]
            
            # If the best group is from an expense-table, we must sum the values
            # because they might represent partial totals across multiple pages.
            # If it's heuristic or unknown, we just pick the max to avoid double counting noisy regexes.
            best_mv_name = PRIORITY_ORDER[best_priority] if best_priority < len(PRIORITY_ORDER) else ""
            if best_mv_name.startswith("expense-table"):
                return f"{sum(best_group):.2f}"
            else:
                return f"{max(best_group):.2f}"

    if field_name == "age":
        nums: list[int] = []
        for v, _mv in clean:
            # Prefer direct numeric candidates and ignore out-of-range matches.
            for m in re.finditer(r"\b(\d{1,3})\b", v):
                n = int(m.group(1))
                if 0 < n < 121:
                    nums.append(n)
        if nums:
            return str(min(nums))

    def _noise_score(v: str) -> tuple[int, int, int]:
        pipes = v.count("|")
        newlines = v.count("\n")
        # Prefer richer but cleaner candidates.
        return (pipes + (2 * newlines), 0 if len(v) >= 4 else 1, -len(v))

    return sorted([v for v, _mv in clean], key=_noise_score)[0].strip()


def _build_parsed_field_map(pf_rows: list[ParsedField]) -> dict[str, str]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    # Stable ordering so tie-break behavior is deterministic.
    sorted_rows = sorted(
        pf_rows,
        key=lambda r: ((r.created_at.isoformat() if r.created_at else ""), str(r.id)),
    )
    for r in sorted_rows:
        grouped.setdefault(r.field_name, []).append(
            (r.field_value or "", r.model_version or "")
        )

    resolved: dict[str, str] = {}
    for field_name, values in grouped.items():
        best = _pick_best_field_value(field_name, values)
        if best:
            resolved[field_name] = best
    return resolved


def _parsed_fields_to_canonical(pf_rows: list[ParsedField]) -> dict[str, Any]:
    parsed = _build_parsed_field_map(pf_rows)

    expenses: list[dict[str, Any]] = []
    seen_expenses: set[tuple[str, float]] = set()
    non_expense_terms = {
        "date of birth",
        "age",
        "phone",
        "email",
        "address",
        "length of stay",
        "diagnosis count",
        "medications",
        "patient name",
    }
    for row in pf_rows:
        if not (row.field_name or "").startswith("expense_table_row_"):
            continue
        raw_value = row.field_value or ""
        if not raw_value:
            continue
        try:
            item = json.loads(raw_value)
        except Exception:
            continue
        if isinstance(item, dict):
            desc = str(item.get("description") or item.get("category") or item.get("name") or "").strip()
            desc_lower = desc.lower()
            if not desc:
                continue
            if any(term in desc_lower for term in non_expense_terms):
                continue

            amount_val = item.get("amount")
            try:
                amount = float(
                    str(amount_val)
                    .replace("Rs.", "")
                    .replace("₹", "")
                    .replace(",", "")
                    .strip()
                )
            except Exception:
                continue
            if amount <= 0:
                continue

            dedupe_key = (desc_lower, amount)
            if dedupe_key in seen_expenses:
                continue
            seen_expenses.add(dedupe_key)

            sanitized = dict(item)
            sanitized["description"] = desc
            sanitized["category"] = str(item.get("category") or desc).strip()
            sanitized["amount"] = f"{amount:.2f}"
            expenses.append(sanitized)

    total_amount = 0.0
    for item in expenses:
        try:
            total_amount += float(item.get("amount", 0) or 0)
        except Exception:
            continue

    claimed_total = parsed.get("claimed_total") or parsed.get("total_amount")
    canonical: dict[str, Any] = {
        "patient": {
            "name": parsed.get("patient_name"),
            "member_id": parsed.get("member_id"),
            "policy_number": parsed.get("policy_number"),
            "age": parsed.get("age"),
            "sex": parsed.get("sex"),
            "address": parsed.get("address"),
        },
        "insurance": {
            "payer": parsed.get("payer"),
            "policy_number": parsed.get("policy_number"),
            "member_id": parsed.get("member_id"),
        },
        "hospitalization": {
            "hospital_name": parsed.get("hospital_name"),
            "admission_date": parsed.get("admission_date"),
            "discharge_date": parsed.get("discharge_date"),
            "doctor_name": parsed.get("doctor_name"),
        },
        "diagnosis": {
            "primary": parsed.get("diagnosis"),
            "secondary": parsed.get("secondary_diagnosis"),
            "procedure": parsed.get("procedure"),
        },
        "claims": {
            "claimed_total": claimed_total,
            "calculated_total": total_amount,
            "total_amount": parsed.get("total_amount") or (f"{total_amount:.2f}" if total_amount > 0 else None),
            "confidence": "HIGH",
        },
        "expenses": {
            "line_items": expenses,
            "item_count": len(expenses),
        },
        "sections": [],
    }
    return canonical


def _canonical_to_parsed_fields(canonical: dict[str, Any] | None) -> dict[str, str]:
    """Extract parsed fields from canonical claim structure.
    
    Handles both legacy and semantic-extracted canonical formats.
    Supports field extraction from fields array and nested structures.
    """
    canonical = canonical or {}
    patient = canonical.get("patient") or {}
    insurance = canonical.get("insurance") or {}
    hospitalization = canonical.get("hospitalization") or {}
    diagnosis = canonical.get("diagnosis") or {}
    claims = canonical.get("claims") or {}

    # First try nested structure, then fallback to top-level semantic extraction
    field_map = {
        "patient_name": patient.get("name"),
        "member_id": patient.get("member_id") or insurance.get("member_id"),
        "policy_number": patient.get("policy_number") or insurance.get("policy_number"),
        "age": patient.get("age"),
        "gender": patient.get("gender") or patient.get("sex"),  # Support both names
        "sex": patient.get("sex") or patient.get("gender"),
        "date_of_birth": patient.get("date_of_birth") or patient.get("dob"),
        "address": patient.get("address"),
        "payer": insurance.get("payer"),
        "hospital_name": hospitalization.get("hospital_name"),
        "admission_date": hospitalization.get("admission_date"),
        "discharge_date": hospitalization.get("discharge_date"),
        "doctor_name": hospitalization.get("doctor_name") or hospitalization.get("treating_doctor"),  # Semantic extraction uses treating_doctor
        "treating_doctor": hospitalization.get("treating_doctor") or hospitalization.get("doctor_name"),
        "ward_type": hospitalization.get("ward_type"),
        "icu_days": hospitalization.get("icu_days"),
        "total_days": hospitalization.get("total_days"),
        "diagnosis": diagnosis.get("primary"),
        "primary_diagnosis": diagnosis.get("primary"),
        "secondary_diagnosis": diagnosis.get("secondary"),
        "procedure": diagnosis.get("procedure"),
        "icd_code": diagnosis.get("icd_code"),
        "icd10_code": diagnosis.get("icd10_code"),
        "total_amount": claims.get("total_amount"),
        "claimed_total": claims.get("claimed_total"),
        "registration_number": hospitalization.get("registration_number") or patient.get("registration_number"),
    }

    # Also check if there's a fields array (from semantic extraction)
    parsed: dict[str, str] = {}
    fields_array = canonical.get("fields") or []
    if isinstance(fields_array, list):
        for field_obj in fields_array:
            if isinstance(field_obj, dict):
                canonical_field = field_obj.get("canonical_field") or field_obj.get("field_name")
                value = field_obj.get("value") or field_obj.get("field_value")
                if canonical_field and value:
                    parsed[canonical_field] = str(value).strip()
    
    # Add from nested structure map
    for key, value in field_map.items():
        if value is None or key in parsed:  # Skip if already set from fields array
            continue
        text = str(value).strip()
        if text:
            parsed[key] = text
    
    return parsed


def _merge_missing_values(target: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Fill in missing values in target from fallback without overwriting edits."""
    for key, value in fallback.items():
        if key not in target:
            target[key] = value
            continue

        current = target[key]
        if isinstance(current, dict) and isinstance(value, dict):
            _merge_missing_values(current, value)
            continue

        if isinstance(current, list) and isinstance(value, list):
            if not current and value:
                target[key] = value
            continue

        if (current is None or current == "" or current == {} or current == []) and value not in (None, "", {}, []):
            target[key] = value

    return target


def _rebuild_claim_canonical(db: Session, claim: Claim) -> dict[str, Any]:
    """Rebuild canonical JSON from the latest parsed fields, preserving any legacy extras."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    rebuilt = _parsed_fields_to_canonical(pf_rows) if pf_rows else {}
    legacy = claim.canonical_json or {}
    if rebuilt and legacy:
        return _merge_missing_values(rebuilt, legacy)
    return rebuilt or legacy


# ------------------------------------------------------------------ helpers

def _gather_claim_data(db: Session, claim: Claim) -> dict[str, Any]:
    """Collect all data needed for submission payload from canonical JSON."""
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()

    canonical = claim.canonical_json
    if not canonical:
        pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
        canonical = _parsed_fields_to_canonical(pf_rows) if pf_rows else {}

    parsed_map = _canonical_to_parsed_fields(canonical)

    return {
        "claim_id": str(claim.id),
        "policy_id": claim.policy_id,
        "patient_id": claim.patient_id,
        "parsed_fields": parsed_map,
        "icd_codes": [c.code for c in codes if c.code_system == "ICD10"],
        "cpt_codes": [c.code for c in codes if c.code_system == "CPT"],
    }


def _gather_claim_data_full(db: Session, claim: Claim) -> dict[str, Any]:
    """Collect all data for TPA PDF generation from canonical JSON."""
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()
    docs = db.query(Document).filter(Document.claim_id == claim.id).all()
    canonical = claim.canonical_json or {}
    if not canonical:
        pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
        canonical = _parsed_fields_to_canonical(pf_rows) if pf_rows else {}
    if not canonical:
        logger.warning("[TRACE] Canonical claim payload is missing for claim %s", claim.id)
        raise HTTPException(status_code=409, detail="Canonical claim payload is missing; run parsing first")

    logger.info("[RENDERER_INPUT] Canonical JSON retrieved for claim %s", claim.id)
    # We can't easily write to tmp/parser_debug/runtime/ from here if it's a separate service,
    # but I'll try anyway or just log the content.
    try:
        import json as _json
        import os as _os
        runtime_dir = "tmp/parser_debug/runtime"
        _os.makedirs(runtime_dir, exist_ok=True)
        with open(_os.path.join(runtime_dir, "06_renderer_input_submission.json"), "w") as f:
            _json.dump(canonical, f, indent=2)
    except Exception:
        pass


    identity_rows = db.query(DocValidation).filter(
        DocValidation.claim_id == claim.id,
        DocValidation.doc_type == "IDENTITY_GATE",
    ).all()
    identity_excluded_doc_ids = {
        r.document_id
        for r in identity_rows
        if (r.validation_metadata or {}).get("excluded_from_pipeline")
    }
    identity_warnings = [
        {
            "document_id": str(r.document_id),
            "file_name": (r.validation_metadata or {}).get("file_name", ""),
            "reason": (r.validation_metadata or {}).get("reason", "Manual review required"),
        }
        for r in identity_rows
        if (r.validation_metadata or {}).get("needs_manual_review")
    ]

    # Predictions
    preds = db.query(Prediction).filter(Prediction.claim_id == claim.id).order_by(Prediction.created_at.desc()).limit(3).all()
    predictions = [{"rejection_score": p.rejection_score, "top_reasons": p.top_reasons, "model_name": p.model_name} for p in preds]

    # Validations — re-run rules live so preview always reflects current data
    parsed = _canonical_to_parsed_fields(canonical)
    _codes_for_rules = [{"code": c.code, "code_system": c.code_system, "is_primary": getattr(c, "is_primary", False)} for c in codes]
    _rejection_score = preds[0].rejection_score if preds else None
    _rule_ctx = {"field_map": parsed, "codes": _codes_for_rules, "rejection_score": _rejection_score}
    _rule_results = _run_validation_rules(_rule_ctx) if _run_validation_rules else []
    validations = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "severity": r.severity, "message": r.message, "passed": r.passed} for r in _rule_results]

    top_icd_codes = _sort_icd_codes(codes)[:3]
    icd_list = [{"code": c.code, "description": c.description or "", "confidence": c.confidence, "estimated_cost": getattr(c, "estimated_cost", None), "is_primary": c.is_primary} for c in top_icd_codes]
    cpt_list = [{"code": c.code, "description": c.description or "", "confidence": c.confidence, "estimated_cost": getattr(c, "estimated_cost", None)} for c in codes if c.code_system == "CPT"]

    icd_total = sum(x["estimated_cost"] or 0 for x in icd_list)
    cpt_total = sum(x["estimated_cost"] or 0 for x in cpt_list)

    # Build expense breakdown from canonical JSON — handles semantic extraction and legacy formats.
    expenses: list[dict[str, Any]] = []
    expense_items = (canonical.get("expenses", {}) or {}).get("line_items", []) or []
    
    for item in expense_items:
        if not isinstance(item, dict):
            continue
        
        # Extract amount — handle multiple formats
        amount = None
        for amount_key in ["amount", "total", "price", "cost"]:
            try:
                val = item.get(amount_key, 0) or 0
                if isinstance(val, str):
                    # Remove currency symbols and commas
                    val = val.replace("Rs.", "").replace("₹", "").replace(",", "").strip()
                amount = float(val)
                if amount > 0:
                    break
            except (ValueError, AttributeError, TypeError):
                continue
        
        if not amount or amount <= 0:
            continue
        
        # Extract quantity and unit price if available
        qty = None
        try:
            qty_val = item.get("quantity") or item.get("qty") or item.get("q")
            if qty_val:
                qty = str(qty_val).strip()
        except:
            pass
        
        unit_price = None
        try:
            up_val = item.get("unit_price") or item.get("unit_cost") or item.get("rate")
            if up_val:
                unit_price = float(str(up_val).replace("Rs.", "").replace("₹", "").replace(",", ""))
        except (ValueError, TypeError, AttributeError):
            pass
        
        # Build expense record
        description = item.get("description") or item.get("desc") or item.get("name") or "Medical Expense"
        category = item.get("category") or description
        
        expenses.append({
            "category": category,
            "amount": amount,
            "description": description,
            "quantity": qty,
            "unit_price": unit_price,
        })
        
        logger.debug(f"[EXPENSE] {description}: Rs. {amount}")

    expense_total = sum(e["amount"] for e in expenses)
    claims_block = canonical.get("claims") or {}
    billed_total = 0.0
    gross_total_found = False
    for candidate in (claims_block.get("total_amount"), claims_block.get("claimed_total"), claims_block.get("calculated_total")):
        try:
            billed_total = float(candidate)
        except Exception:
            continue
        if billed_total > 0:
            gross_total_found = True
            break

    if billed_total <= 0 and expense_total > 0:
        billed_total = expense_total

    reconciliation_warnings: list[str] = []
    if expense_total > 0 and billed_total > 0 and abs(expense_total - billed_total) > max(1.0, billed_total * 0.01):
        reconciliation_warnings.append(
            f"Itemised expenses total Rs. {expense_total:,.2f} differs from canonical total Rs. {billed_total:,.2f}."
        )

    radiology_doc_ids: set[str] = set()

    # ── Scan analyses (MRI / CT / X-Ray / Ultrasound) ──
    scan_rows = db.query(ScanAnalysis).filter(ScanAnalysis.claim_id == claim.id).all()
    scan_analyses = []
    for s in scan_rows:
        scan_analyses.append({
            "id": str(s.id),
            "document_id": str(s.document_id),
            "scan_type": s.scan_type,
            "body_part": s.body_part,
            "modality": s.modality,
            "findings": s.findings or [],
            "impression": s.impression,
            "recommendation": s.recommendation,
            "confidence": s.confidence,
            "is_abnormal": (s.scan_metadata or {}).get("is_abnormal", False),
            "file_name": (s.scan_metadata or {}).get("file_name", ""),
        })

    render_payload = {
        "claim_id": str(claim.id),
        "status": claim.status,
        "policy_id": claim.policy_id,
        "patient_id": claim.patient_id,
        "parsed_fields": parsed,
        "icd_codes": icd_list,
        "cpt_codes": cpt_list,
        "cost_summary": {
            "icd_total": round(icd_total, 2),
            "cpt_total": round(cpt_total, 2),
            "grand_total": round(billed_total if billed_total > 0 else (icd_total + cpt_total), 2),
            "anchored_billed_total": round(billed_total, 2),
            "estimated_total": round(icd_total + cpt_total, 2),
        },
        "expenses": expenses,
        "expense_total": round(expense_total, 2),
        "billed_total": round(billed_total, 2),
        "gross_total_found": gross_total_found,
        "has_radiology_source": bool(radiology_doc_ids),
        "reconciliation_warnings": reconciliation_warnings,
        "predictions": predictions,
        "validations": validations,
        "ocr_excerpt": "",
        "documents": [{"file_name": d.file_name, "file_type": d.file_type, "doc_id": str(d.id)} for d in docs],
        "document_texts": {str(d.id): "" for d in docs},
        "scan_analyses": scan_analyses,
        "identity_review": {
            "excluded_document_ids": [str(i) for i in identity_excluded_doc_ids],
            "manual_review_required": len(identity_warnings) > 0,
            "warnings": identity_warnings,
        },
    }
    
    logger.info("[FINAL_RENDER_DATA] Payload constructed")
    try:
        import json as _json
        import os as _os
        runtime_dir = "tmp/parser_debug/runtime"
        _os.makedirs(runtime_dir, exist_ok=True)
        with open(_os.path.join(runtime_dir, "07_final_render_payload.json"), "w") as f:
            _json.dump(render_payload, f, indent=2)
    except Exception:
        pass
        
    return render_payload



# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    irda_modern_ok = generate_irda_pdf_modern is not None
    irda_warning = (
        None
        if irda_modern_ok
        else "WeasyPrint not installed — IRDA form will fall back to legacy renderer. Run `pip install -r requirements.txt`."
    )
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "irda_renderer": {
            "modern_available": irda_modern_ok,
            "legacy_available": True,
            "warning": irda_warning,
        },
    }


# ── TPA Directory (DB-backed) ──

# Fallback seed data — used only if DB table is empty (first boot)
_TPA_SEED = [
    ("icici_lombard",       "ICICI Lombard",            "🏦", "Private", "claims@icicilombard.com",       "1800-266-7700", "https://www.icicilombard.com"),
    ("star_health",         "Star Health",              "⭐", "Private", "claims@starhealth.in",          "1800-425-2255", "https://www.starhealth.in"),
    ("hdfc_ergo",           "HDFC ERGO",                "🔷", "Private", "claims@hdfcergo.com",           "1800-266-0700", "https://www.hdfcergo.com"),
    ("bajaj_allianz",       "Bajaj Allianz",            "🛡️", "Private", "claims@bajajallianz.co.in",     "1800-209-5858", "https://www.bajajallianz.com"),
    ("new_india",           "New India Assurance",       "🇮🇳", "PSU",     "claims@newindia.co.in",        "1800-209-1415", "https://www.newindia.co.in"),
    ("niva_bupa",           "Niva Bupa",                "💙", "Private", "claims@nivabupa.com",           "1800-200-5577", "https://www.nivabupa.com"),
    ("care_health",         "Care Health",              "💚", "Private", "claims@careinsurance.com",      "1800-102-4488", "https://www.careinsurance.com"),
    ("tata_aig",            "Tata AIG",                 "🔶", "Private", "claims@tataaig.com",            "1800-266-7780", "https://www.tataaig.com"),
    ("sbi_general",         "SBI General",              "🏛️", "PSU",     "claims@sbigeneral.in",          "1800-102-1111", "https://www.sbigeneral.in"),
    ("oriental_insurance",  "Oriental Insurance",        "🌅", "PSU",     "claims@orientalinsurance.co.in","1800-118-485",  "https://www.orientalinsurance.org.in"),
    ("max_bupa",            "Max Bupa",                 "🟣", "Private", "claims@maxbupa.com",            "1800-200-5577", "https://www.maxbupa.com"),
    ("manipal_cigna",       "ManipalCigna",             "🩺", "Private", "claims@manipalcigna.com",       "1800-266-0800", "https://www.manipalcigna.com"),
    ("united_india",        "United India Insurance",    "🏛️", "PSU",     "claims@uiic.co.in",            "1800-425-33-33","https://www.uiic.co.in"),
    ("national_insurance",  "National Insurance",        "🏛️", "PSU",     "claims@nic.co.in",             "1800-345-0330", "https://www.nationalinsurance.nic.co.in"),
    ("iffco_tokio",         "IFFCO Tokio",              "🟢", "Private", "claims@iffcotokio.co.in",       "1800-103-5499", "https://www.iffcotokio.co.in"),
    ("reliance_general",    "Reliance General",          "🔴", "Private", "claims@reliancegeneral.co.in",  "1800-102-1010", "https://www.reliancegeneral.co.in"),
    ("cholamandalam",       "Cholamandalam MS",          "🟡", "Private", "claims@cholams.murugappa.com",  "1800-200-5544", "https://www.cholainsurance.com"),
    ("aditya_birla",        "Aditya Birla Health",       "🌐", "Private", "claims@adityabirlacapital.com", "1800-270-7000", "https://www.adityabirlahealthinsurance.com"),
    ("medi_assist",         "Medi Assist (TPA)",         "🏥", "TPA",     "claims@mediassist.in",          "1800-425-3030", "https://www.mediassist.in"),
    ("paramount_health",    "Paramount Health (TPA)",    "🏥", "TPA",     "claims@paramounttpa.com",       "1800-233-8181", "https://www.paramounttpa.com"),
    ("vidal_health",        "Vidal Health (TPA)",        "🏥", "TPA",     "claims@vidalhealth.com",        "1800-425-4033", "https://www.vidalhealth.com"),
    ("heritage_health",     "Heritage Health (TPA)",     "🏥", "TPA",     "claims@heritagehealthtpa.com",  "1800-102-4488", "https://www.heritagehealthtpa.com"),
    ("md_india",            "MD India (TPA)",            "🏥", "TPA",     "claims@maborehealthcaretpa.com","1800-233-3010", "https://www.maborehealthcaretpa.com"),
    ("digital_insurance",   "Go Digit General",          "💜", "Private", "claims@godigit.com",            "1800-258-5956", "https://www.godigit.com"),
    ("kotak_general",       "Kotak Mahindra General",    "🔴", "Private", "claims@kotakgi.com",            "1800-266-4545", "https://www.kotakgeneralinsurance.com"),
]


def _ensure_tpa_table(db: Session):
    """Create tpa_providers table if missing and seed data."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    if not insp.has_table("tpa_providers"):
        TpaProvider.__table__.create(engine)
        logger.info("Created tpa_providers table")

    count = db.query(TpaProvider).count()
    if count == 0:
        for code, name, logo, ptype, email, phone, website in _TPA_SEED:
            db.add(TpaProvider(code=code, name=name, logo=logo, provider_type=ptype, email=email, phone=phone, website=website))
        db.commit()
        logger.info("Seeded %d TPA providers", len(_TPA_SEED))


@router.get("/tpa-list")
def list_tpas(db: Session = Depends(get_db)):
    """Return available TPA/Insurance providers from DB."""
    _ensure_tpa_table(db)
    rows = db.query(TpaProvider).filter(TpaProvider.is_active).order_by(TpaProvider.name).all()
    return {
        "tpas": [
            {
                "id": t.code,
                "name": t.name,
                "logo": t.logo or "🏥",
                "type": t.provider_type or "Private",
                "email": t.email or "",
                "phone": t.phone or "",
                "website": t.website or "",
            }
            for t in rows
        ]
    }


@router.post("/submit/{claim_id}", response_model=SubmissionOut)
def submit_claim(
    claim_id: str,
    body: SubmitRequest = SubmitRequest(),
    db: Session = Depends(get_db),
):
    """
    Translate claim data to payer format and submit.
    Uses a payer adapter (plugin architecture).
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    payer = body.payer or settings.default_payer
    adapter = get_adapter(payer)

    claim_data = _gather_claim_data(db, claim)
    payload = adapter.build_payload(claim_data)
    status, response = adapter.submit(payload)

    sub = Submission(
        claim_id=cid,
        payer=payer,
        request_payload=payload,
        response_payload=response,
        status=status,
    )
    db.add(sub)

    claim.status = "SUBMITTED"
    db.commit()
    db.refresh(sub)

    logger.info("Claim %s submitted to payer '%s' — status=%s", cid, payer, status)

    return SubmissionOut(
        submission_id=sub.id,
        claim_id=sub.claim_id,
        payer=sub.payer,
        status=sub.status,
        submitted_at=sub.submitted_at,
    )


@router.get("/{submission_id}", response_model=SubmissionDetailOut)
def get_submission(submission_id: str, db: Session = Depends(get_db)):
    """Retrieve submission details including request/response payloads."""
    sid = _parse_uuid(submission_id)

    sub = db.query(Submission).filter(Submission.id == sid).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    return SubmissionDetailOut(
        submission_id=sub.id,
        claim_id=sub.claim_id,
        payer=sub.payer,
        status=sub.status,
        request_payload=sub.request_payload,
        response_payload=sub.response_payload,
        submitted_at=sub.submitted_at,
    )


@router.get("/claims/{claim_id}/tpa-pdf")
def generate_tpa_claim_pdf(claim_id: str, db: Session = Depends(get_db)):
    """Generate a TPA-readable PDF for the given claim."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    claim_data = _gather_claim_data_full(db, claim)
    pdf_bytes = bytes(generate_tpa_pdf(claim_data))

    # Build filename from patient name + policy number
    pf = claim_data.get("parsed_fields", {})
    patient = (pf.get("patient_name") or pf.get("member_name") or pf.get("insured_name") or "").strip()
    policy = (pf.get("policy_number") or pf.get("policy_id") or pf.get("policy_no") or claim.policy_id or "").strip()
    # Sanitize for filename: replace spaces with underscores, remove special chars
    import re as _re
    safe_patient = _re.sub(r'[^\w\s-]', '', patient).strip().replace(' ', '_') if patient else ""
    safe_policy = _re.sub(r'[^\w\s-]', '', policy).strip().replace(' ', '_') if policy else ""
    if safe_patient and safe_policy:
        filename = f"{safe_patient}_{safe_policy}.pdf"
    elif safe_patient:
        filename = f"{safe_patient}_Claim.pdf"
    elif safe_policy:
        filename = f"Claim_{safe_policy}.pdf"
    else:
        filename = f"TPA_Claim_{str(cid)[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/claims/{claim_id}/irda-pdf")
def generate_irda_claim_pdf(
    claim_id: str,
    blank: bool = False,
    style: str = "legacy",
    db: Session = Depends(get_db),
):
    """Generate the IRDA standard reimbursement claim form (Part A + Part B) PDF.

    Two visual styles are supported:

    * ``style=legacy`` *(default)* — the original tabular fpdf2 rendition that returns
      an *interactive* AcroForm PDF (every value cell, Yes/No radio and
      checklist box becomes an editable widget). Stable and reliable.
    * ``style=modern`` — a polished HTML/CSS rendition with a
      gradient cover page, section cards, and a tabular expense breakdown.
      Print-ready PDF (not interactive). Requires working WeasyPrint environment.

    Pass ``?blank=1`` to download an empty template with the same layout
    (only policy / patient identifiers retained) for manual filling.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    claim_data = _gather_claim_data_full(db, claim)

    use_modern = style.lower() == "modern" and generate_irda_pdf_modern is not None
    renderer_used = "legacy"
    renderer_warning = ""
    if style.lower() == "modern" and generate_irda_pdf_modern is None:
        renderer_warning = (
            "WeasyPrint not installed — falling back to legacy fpdf2 renderer. "
            "Install with: pip install -r requirements.txt"
        )
        logging.getLogger("submission").warning(
            "IRDA modern style requested but WeasyPrint is unavailable; using legacy renderer",
        )
    if use_modern:
        try:
            pdf_bytes = bytes(generate_irda_pdf_modern(claim_data, blank=blank))
            renderer_used = "modern"
        except Exception as exc:
            logging.getLogger("submission").exception(
                "Modern IRDA renderer failed, falling back to legacy: %s", exc,
            )
            pdf_bytes = bytes(generate_irda_pdf(claim_data, blank=blank))
            renderer_warning = f"Modern renderer failed ({type(exc).__name__}); served legacy."
            use_modern = False
    else:
        pdf_bytes = bytes(generate_irda_pdf(claim_data, blank=blank))

    pf = claim_data.get("parsed_fields", {})
    patient = (pf.get("patient_name") or pf.get("member_name") or pf.get("insured_name") or "").strip()
    policy = (pf.get("policy_number") or pf.get("policy_id") or pf.get("policy_no") or claim.policy_id or "").strip()
    import re as _re
    safe_patient = _re.sub(r'[^\w\s-]', '', patient).strip().replace(' ', '_') if patient else ""
    safe_policy = _re.sub(r'[^\w\s-]', '', policy).strip().replace(' ', '_') if policy else ""
    prefix = "IRDA_BlankForm" if blank else "IRDA_ClaimForm"
    if safe_patient and safe_policy:
        filename = f"{prefix}_{safe_patient}_{safe_policy}.pdf"
    elif safe_patient:
        filename = f"{prefix}_{safe_patient}.pdf"
    elif safe_policy:
        filename = f"{prefix}_{safe_policy}.pdf"
    else:
        filename = f"{prefix}_{str(cid)[:8]}.pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-IRDA-Renderer": renderer_used,
    }
    if renderer_warning:
        headers["X-IRDA-Warning"] = renderer_warning
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=headers,
    )


@router.get("/claims/{claim_id}/preview")
def preview_claim_data(claim_id: str, db: Session = Depends(get_db)):
    """Return full structured claim data as JSON for in-app PDF preview before submission."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    data = _gather_claim_data_full(db, claim)

    # Attach feedback map: { field_name: { original, corrected, updated_at } }
    # so the UI can highlight user-edited fields and offer a one-click revert.
    fb_rows = (
        db.query(ClaimFieldFeedback)
        .filter(ClaimFieldFeedback.claim_id == cid)
        .all()
    )
    data["field_feedback"] = {
        row.field_name: {
            "original": row.original_value,
            "corrected": row.corrected_value,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "user_email": row.user_email,
            "document_id": str(row.document_id) if row.document_id else None,
        }
        for row in fb_rows
    }

    # Enrich with formatted summary for UI display
    fields = data.get("parsed_fields", {})
    data["summary"] = {
        "patient_name": fields.get("patient_name") or fields.get("member_name") or fields.get("insured_name", "N/A"),
        "policy_number": fields.get("policy_number") or fields.get("policy_id") or fields.get("policy_no") or data.get("policy_id", "N/A"),
        "age": fields.get("age", "N/A"),
        "gender": fields.get("gender", "N/A"),
        "hospital": fields.get("hospital_name") or fields.get("hospital", "N/A"),
        "doctor": fields.get("doctor_name") or fields.get("provider_name") or fields.get("rendering_provider", "N/A"),
        "admission_date": fields.get("admission_date") or fields.get("service_date") or fields.get("date_of_admission", "N/A"),
        "discharge_date": fields.get("discharge_date", "N/A"),
        "diagnosis": fields.get("diagnosis") or fields.get("primary_diagnosis") or fields.get("chief_complaint", "N/A"),
        "history_of_present_illness": fields.get("history_of_present_illness") or fields.get("present_illness") or fields.get("hopi", "N/A"),
        "past_history": fields.get("past_history") or fields.get("medical_history") or fields.get("past_history_months", "N/A"),
        "disease_history": fields.get("disease_history") or fields.get("history_of_disease") or fields.get("known_comorbidities", "N/A"),
        "allergies": fields.get("allergies") or fields.get("known_allergies", "N/A"),
        "treatment": fields.get("treatment") or fields.get("treatment_given") or fields.get("procedure_performed", "N/A"),
        "discharge_summary": fields.get("discharge_summary") or fields.get("discharge_notes", "N/A"),
        "bank_name": fields.get("bank_name", "N/A"),
        "bank_branch": fields.get("bank_branch", "N/A"),
        "account_holder": fields.get("account_holder") or fields.get("bank_account_name", "N/A"),
        "account_number": fields.get("account_number") or fields.get("bank_account_number", "N/A"),
        "ifsc_code": fields.get("ifsc_code") or fields.get("ifsc", "N/A"),
        "total_amount": (
            f"{data.get('billed_total', 0):.2f}"
            if isinstance(data.get("billed_total"), (int, float)) and data.get("billed_total", 0) > 0
            else (fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount", "N/A"))
        ),
        "icd_count": len(data.get("icd_codes", [])),
        "cpt_count": len(data.get("cpt_codes", [])),
        "risk_score": data["predictions"][0]["rejection_score"] if data.get("predictions") else None,
        "validation_passed": sum(1 for v in data.get("validations", []) if v.get("passed")),
        "validation_total": len(data.get("validations", [])),
        "manual_review_required": bool((data.get("identity_review") or {}).get("manual_review_required")),
    }

    # AI Brain insights — synthesized intelligence from all documents
    data["brain_insights"] = _generate_brain_insights(data)

    # Cross-document reimbursement intelligence
    data["reimbursement_brain"] = _generate_reimbursement_brain(data)

    return data


@router.post("/claims/{claim_id}/code-feedback")
def submit_code_feedback(claim_id: str, db: Session = Depends(get_db), body: dict = None):
    """
    Submit feedback on medical code suggestions for reinforcement learning.
    Body: {"code": "I21.9", "action": "accept|reject|correct", "corrected_code": "I21.3"}
    """
    if body is None:
        body = {}
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    code = body.get("code", "")
    action = body.get("action", "")  # accept, reject, correct
    corrected_code = body.get("corrected_code")

    if action not in ("accept", "reject", "correct"):
        raise HTTPException(status_code=400, detail="action must be accept, reject, or correct")

    if action == "correct" and not corrected_code:
        raise HTTPException(status_code=400, detail="corrected_code required for correct action")

    # Update the medical_code record confidence based on feedback
    codes = db.query(MedicalCode).filter(
        MedicalCode.claim_id == cid,
        MedicalCode.code == code,
    ).all()

    for mc in codes:
        if action == "accept":
            mc.confidence = min(1.0, (mc.confidence or 0.5) + 0.1)
        elif action == "reject":
            mc.confidence = max(0.0, (mc.confidence or 0.5) - 0.3)
        elif action == "correct" and corrected_code:
            mc.confidence = max(0.0, (mc.confidence or 0.5) - 0.2)
            # Add the corrected code
            db.add(MedicalCode(
                claim_id=cid,
                code=corrected_code,
                code_system=mc.code_system,
                description=f"User-corrected from {code}",
                confidence=0.95,
                is_primary=str(mc.is_primary),
            ))

    db.commit()
    logger.info("Code feedback: claim=%s code=%s action=%s", str(cid)[:8], code, action)
    return {"status": "ok", "message": f"Code {code} feedback recorded: {action}"}


@router.put("/claims/{claim_id}/icd-codes")
def update_icd_codes(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: TokenPayload | None = Depends(get_current_user),
):
    """Replace the ICD-10 codes for a claim from the preview UI."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    codes_payload = body.get("codes", [])
    if not isinstance(codes_payload, list):
        raise HTTPException(status_code=400, detail="codes must be a list")

    # Replace only ICD-10 rows; CPT rows stay untouched.
    db.query(MedicalCode).filter(
        MedicalCode.claim_id == cid,
        MedicalCode.code_system == "ICD10",
    ).delete()

    added = 0
    for idx, item in enumerate(codes_payload):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        description = str(item.get("description") or "").strip() or None
        confidence = item.get("confidence")
        estimated_cost = item.get("estimated_cost")
        try:
            confidence_val = float(confidence) if confidence not in (None, "") else None
        except Exception:
            confidence_val = None
        try:
            estimated_cost_val = float(estimated_cost) if estimated_cost not in (None, "") else None
        except Exception:
            estimated_cost_val = None

        db.add(MedicalCode(
            claim_id=cid,
            code=code,
            code_system="ICD10",
            description=description,
            confidence=confidence_val,
            is_primary=bool(item.get("is_primary")) or idx == 0,
            estimated_cost=estimated_cost_val,
        ))
        added += 1

    if added == 0:
        raise HTTPException(status_code=400, detail="At least one ICD-10 code is required")

    db.commit()
    logger.info("Updated ICD-10 codes for claim=%s by user=%s", str(cid)[:8], getattr(user, "email", None) if user else None)
    return {"status": "ok", "icd_count": added}


@router.put("/claims/{claim_id}/fields")
def update_claim_fields(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: TokenPayload | None = Depends(get_current_user),
):
    """Update parsed fields for a claim.

    Body: ``{"fields": {"patient_name": "...", ...}}``

    Side effects:
      * Upserts rows in ``parsed_fields`` (so the PDF and preview reflect edits).
      * Records a row in ``claim_field_feedback`` with the original parsed value
        (frozen on first edit) + the latest correction + the calling user.
        This powers the UI "original vs current" diff and revert button.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    fields = body.get("fields", {})
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided")

    user_sub = user.sub if user else None
    user_email = user.email if user else None

    updated = 0
    feedback_rows = 0
    for field_name, field_value in fields.items():
        new_val = str(field_value) if field_value is not None else ""

        existing = (
            db.query(ParsedField)
            .filter(
                ParsedField.claim_id == cid,
                ParsedField.field_name == field_name,
            )
            .first()
        )
        prev_val = existing.field_value if existing else None

        # Skip no-op edits — don't pollute the feedback table.
        if existing and (prev_val or "") == new_val:
            continue

        if existing:
            existing.field_value = new_val
        else:
            db.add(
                ParsedField(
                    claim_id=cid,
                    field_name=field_name,
                    field_value=new_val,
                )
            )
        updated += 1

    db.flush()
    claim.canonical_json = _rebuild_claim_canonical(db, claim)
    db.commit()
    logger.info(
        "Updated %d field(s) (%d feedback) for claim %s by %s",
        updated,
        feedback_rows,
        str(cid)[:8],
        user_email or user_sub or "anonymous",
    )
    return {"status": "ok", "updated": updated, "feedback_recorded": feedback_rows}


@router.post("/claims/{claim_id}/fields/{field_name}/revert")
def revert_claim_field(
    claim_id: str,
    field_name: str,
    db: Session = Depends(get_db),
    user: TokenPayload | None = Depends(get_current_user),
):
    """Revert a single edited field back to its original (parser-extracted) value.

    Restores ``parsed_fields.field_value`` to the frozen ``original_value``
    captured in ``claim_field_feedback`` and removes the feedback row, so the
    field is once again "clean" (no edited badge).
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    fb = (
        db.query(ClaimFieldFeedback)
        .filter(
            ClaimFieldFeedback.claim_id == cid,
            ClaimFieldFeedback.field_name == field_name,
            ClaimFieldFeedback.document_id.is_(None),
        )
        .first()
    )
    if fb is None:
        raise HTTPException(
            status_code=404,
            detail=f"No feedback recorded for field '{field_name}'",
        )

    original = fb.original_value
    parsed = (
        db.query(ParsedField)
        .filter(
            ParsedField.claim_id == cid,
            ParsedField.field_name == field_name,
        )
        .first()
    )
    if parsed is not None:
        parsed.field_value = original or ""
    else:
        db.add(
            ParsedField(
                claim_id=cid,
                field_name=field_name,
                field_value=original or "",
            )
        )

    db.delete(fb)
    db.commit()
    actor = (user.email if user else None) or (user.sub if user else None) or "anonymous"
    logger.info(
        "Reverted field %s on claim %s (by %s)",
        field_name,
        str(cid)[:8],
        actor,
    )
    return {
        "status": "ok",
        "field_name": field_name,
        "reverted_to": original,
    }


@router.put("/claims/{claim_id}/expenses")
def update_claim_expenses(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Replace itemized expense parsed_fields for a claim with the provided list.
    Body: {"expenses": [{"category": "Room Charges", "amount": 1234.56}, ...]}

    This stores each row as a ParsedField with model_version="expense-table-ui"
    so the preview and PDF generation will include the updated itemised rows.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    expenses = body.get("expenses") or []
    if not isinstance(expenses, list):
        raise HTTPException(status_code=400, detail="expenses must be a list")

    # Delete existing expense-like parsed fields (heuristic).
    # Match by either model_version (new UI rows) OR by field_name prefix (legacy rows)
    try:
        # Fetch rows to delete so we can log them and ensure deletion across DB backends
        del_q = db.query(ParsedField).filter(
            ParsedField.claim_id == cid,
        ).filter(
            (ParsedField.model_version.ilike("expense-table%")) | (ParsedField.field_name.ilike("expense_table_row_%"))
        )
        rows_to_delete = del_q.all()
        deleted = 0
        if rows_to_delete:
            logger.info("Deleting %d existing expense parsed_fields for claim %s", len(rows_to_delete), str(cid)[:8])
            for r in rows_to_delete:
                try:
                    db.delete(r)
                    deleted += 1
                except Exception:
                    logger.debug("Failed to delete parsed_field %s for claim %s", getattr(r, 'id', None), str(cid)[:8], exc_info=True)
    except Exception:
        deleted = 0

    import json as _json
    created = 0
    for i, e in enumerate(expenses):
        try:
            cat = str(e.get("category") or f"Expense {i+1}")[:200]
            amt = float(e.get("amount") or 0)
            # Store a single ParsedField per expense with JSON value {category, amount}
            pf = ParsedField(
                claim_id=cid,
                document_id=None,
                field_name=f"expense_table_row_{i+1}",
                field_value=_json.dumps({"category": cat, "amount": amt}),
                model_version="expense-table-ui",
            )
            db.add(pf)
            created += 1
        except Exception:
            continue

    db.flush()
    claim.canonical_json = _rebuild_claim_canonical(db, claim)
    db.commit()
    logger.info("Replaced expenses for claim %s: deleted=%d created=%d", str(cid)[:8], deleted, created)
    return {"status": "ok", "deleted": deleted, "created": created}


@router.get("/claims/{claim_id}/audit")
def get_audit_log(claim_id: str, db: Session = Depends(get_db)):
    """Return the full audit trail for a claim."""
    from sqlalchemy import text
    cid = _parse_uuid(claim_id)
    # verify claim exists
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    rows = db.execute(
        text("SELECT id, actor, action, metadata, created_at FROM audit_logs WHERE claim_id = :cid ORDER BY created_at ASC"),
        {"cid": str(cid)},
    ).fetchall()

    entries = []
    for r in rows:
        import json
        meta = r[3]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                pass
        entries.append({
            "id": str(r[0]),
            "actor": r[1],
            "action": r[2],
            "metadata": meta,
            "created_at": r[4].isoformat() if r[4] else None,
        })

    return {"claim_id": str(cid), "audit_trail": entries, "total": len(entries)}


@router.post("/claims/{claim_id}/send-to-tpa")
def send_to_tpa(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Send a claim to a specific TPA. Generates the TPA PDF, records the submission,
    and simulates dispatch to the selected TPA.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    tpa_id = body.get("tpa_id", "")
    tpa = db.query(TpaProvider).filter(TpaProvider.code == tpa_id, TpaProvider.is_active).first()
    if not tpa:
        raise HTTPException(status_code=400, detail="Invalid TPA selected")

    # Gather claim data and build submission
    claim_data = _gather_claim_data(db, claim)
    adapter = get_adapter("generic")
    payload = adapter.build_payload(claim_data)

    reference = f"TPA-{tpa.code.upper()[:8]}-{str(cid)[:8]}"

    # Record submission with TPA details
    sub = Submission(
        claim_id=cid,
        payer=tpa.name,
        request_payload={**payload, "tpa_id": tpa.code, "tpa_email": tpa.email or ""},
        response_payload={
            "ack": True,
            "reference": reference,
            "tpa_name": tpa.name,
            "message": f"Claim dispatched to {tpa.name} for processing",
            "status": "DISPATCHED",
        },
        status="SUBMITTED",
    )
    db.add(sub)

    claim.status = "SUBMITTED"
    db.commit()
    db.refresh(sub)

    logger.info("Claim %s sent to TPA '%s' — ref=%s", str(cid)[:8], tpa.name, reference)

    return {
        "status": "success",
        "submission_id": str(sub.id),
        "tpa_name": tpa.name,
        "reference": reference,
        "message": f"Claim successfully sent to {tpa.name}",
    }


# ── TPA Decision Actions ──────────────────────────────────────────

_TPA_ACTION_STATUS = {
    "approve": "APPROVED",
    "reject": "REJECTED",
    "send_back": "MODIFICATION_REQUESTED",
    "request_docs": "DOCUMENTS_REQUESTED",
    "send_money": "SETTLED",
}

@router.post("/claims/{claim_id}/tpa-action")
def tpa_claim_action(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    TPA decision endpoint.  Supported actions:
    - approve   → status = APPROVED
    - reject    → status = REJECTED
    - send_back → status = MODIFICATION_REQUESTED
    - request_docs → status = DOCUMENTS_REQUESTED
    - send_money → status = SETTLED

    Body: {"action": "approve|reject|send_back|request_docs|send_money",
           "reason": "optional text", "requested_documents": ["list of doc types"]}
    """
    from sqlalchemy import text
    from datetime import datetime, timezone
    import json

    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    action = (body.get("action") or "").strip().lower()
    if action not in _TPA_ACTION_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Must be one of: {', '.join(_TPA_ACTION_STATUS)}",
        )

    reason = (body.get("reason") or "").strip()
    requested_docs = body.get("requested_documents") or []
    annotations = body.get("annotations") or []

    new_status = _TPA_ACTION_STATUS[action]
    old_status = claim.status
    claim.status = new_status
    db.flush()

    # Record in audit_logs
    try:
        db.execute(
            text(
                "INSERT INTO audit_logs (id, claim_id, actor, action, metadata, created_at) "
                "VALUES (:id, :cid, :actor, :action, :meta, :ts)"
            ),
            {
                "id": str(uuid.uuid4()),
                "cid": str(cid),
                "actor": "tpa-reviewer",
                "action": f"CLAIM_{action.upper()}",
                "meta": json.dumps({
                    "old_status": old_status,
                    "new_status": new_status,
                    "reason": reason,
                    "requested_documents": requested_docs,
                    **({"annotations": annotations} if annotations else {}),
                }),
                "ts": datetime.now(timezone.utc),
            },
        )
    except Exception:
        logger.debug("Audit write failed for tpa-action", exc_info=True)

    db.commit()

    logger.info("TPA action '%s' on claim %s: %s → %s | reason=%s",
                action, str(cid)[:8], old_status, new_status, reason[:80] if reason else "(none)")

    return {
        "status": "success",
        "action": action,
        "claim_id": str(cid),
        "old_status": old_status,
        "new_status": new_status,
        "reason": reason,
        "requested_documents": requested_docs,
        "message": {
            "approve": "Claim has been approved",
            "reject": f"Claim has been rejected{f': {reason}' if reason else ''}",
            "send_back": f"Claim sent back for modification{f': {reason}' if reason else ''}",
            "request_docs": f"Additional documents requested: {', '.join(requested_docs) if requested_docs else reason}",
        }.get(action, "Action completed"),
    }


# ── Include router (standalone mode) ──
app.include_router(router)
