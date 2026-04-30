from __future__ import annotations

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


def _infer_document_type(file_name: str, text: str) -> str:
    sample = f"{(file_name or '').lower()}\n{(text or '').lower()}"
    if "medical insurance claim form" in sample:
        return "HOSPITAL_BILL"
    if "hospitalization details" in sample and ("date of admission" in sample or "admission date" in sample):
        return "HOSPITAL_BILL"
    if "itemized inpatient hospital bill" in sample or "gross total" in sample or "bill summary" in sample:
        return "HOSPITAL_BILL"
    if any(k in sample for k in ("radiology", "x-ray", "xray", "ct scan", "mri", "ultrasound", "usg", "sonography", "imaging report")):
        return "RADIOLOGY_REPORT"
    if "discharge summary" in sample:
        return "DISCHARGE_SUMMARY"
    if "pharmacy invoice" in sample:
        return "PHARMACY_INVOICE"
    if "laboratory" in sample or "investigation report" in sample or "lab charges" in sample:
        return "LAB_REPORT"
    return "UNKNOWN"


def _extract_gross_total(text: str) -> float | None:
    if not text:
        return None
    patterns = [
        re.compile(r"gross\s*total\s*[:|\-]?\s*(?:rs|inr|usd|\$|₹)?\.?\s*([\d,]+\.?\d*)", re.I),
        re.compile(r"total\s*amount\s*[:|\-]?\s*(?:rs|inr|usd|\$|₹)?\.?\s*([\d,]+\.?\d*)", re.I),
        re.compile(r"bill\s*summary[\s\S]{0,350}?gross\s*total\s*[:|\-]?\s*(?:rs|inr|usd|\$|₹)?\.?\s*([\d,]+\.?\d*)", re.I),
    ]
    for pat in patterns:
        matches = [m.group(1) for m in pat.finditer(text)]
        for raw in reversed(matches):
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def _extract_hospital_bill_subtotals(text: str) -> dict[str, float]:
    """Extract canonical A-E subtotals from a hospital bill summary block."""
    if not text:
        return {}

    subtotal_patterns = {
        "room_charges": [
            re.compile(r"sub[-\s]*total\s*A\s*(?:[-–]\s*room\s*&?\s*boarding)?\s*\|?\s*(?:rs|inr)?\s*([\d,]+\.?\d*)", re.I),
        ],
        "investigation_charges": [
            re.compile(r"sub[-\s]*total\s*B\s*(?:[-–]\s*investigations?)?\s*\|?\s*(?:rs|inr)?\s*([\d,]+\.?\d*)", re.I),
        ],
        "surgery_charges": [
            re.compile(r"sub[-\s]*total\s*C\s*(?:[-–]\s*procedures?\s*/\s*implants?)?\s*\|?\s*(?:rs|inr)?\s*([\d,]+\.?\d*)", re.I),
        ],
        "consultation_charges": [
            re.compile(r"sub[-\s]*total\s*D\s*(?:[-–]\s*consultations?)?\s*\|?\s*(?:rs|inr)?\s*([\d,]+\.?\d*)", re.I),
        ],
        "pharmacy_charges": [
            re.compile(r"sub[-\s]*total\s*E\s*(?:[-–]\s*pharmacy\s*&\s*consumables?)?\s*\|?\s*(?:rs|inr)?\s*([\d,]+\.?\d*)", re.I),
        ],
    }

    extracted: dict[str, float] = {}
    for key, patterns in subtotal_patterns.items():
        for pat in patterns:
            matches = [m.group(1) for m in pat.finditer(text)]
            if not matches:
                continue
            for raw in reversed(matches):
                try:
                    value = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if value > 0:
                    extracted[key] = value
                    break
            if key in extracted:
                break

    return extracted


# ------------------------------------------------------------------ helpers

def _gather_claim_data(db: Session, claim: Claim) -> dict[str, Any]:
    """Collect all data needed for submission payload."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()

    parsed_map = _build_parsed_field_map(pf_rows)

    return {
        "claim_id": str(claim.id),
        "policy_id": claim.policy_id,
        "patient_id": claim.patient_id,
        "parsed_fields": parsed_map,
        "icd_codes": [c.code for c in codes if c.code_system == "ICD10"],
        "cpt_codes": [c.code for c in codes if c.code_system == "CPT"],
    }


def _gather_claim_data_full(db: Session, claim: Claim) -> dict[str, Any]:
    """Collect all data for TPA PDF generation (richer than submission)."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()
    docs = db.query(Document).filter(Document.claim_id == claim.id).all()

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

    # OCR text
    doc_ids = [d.id for d in docs]
    ocr_text = ""
    doc_ocr_map: dict[str, str] = {}  # doc_id -> full OCR text
    if doc_ids:
        rows = db.query(OcrResult).filter(OcrResult.document_id.in_(doc_ids)).order_by(OcrResult.page_number).all()
        # Build per-document OCR text
        for r in rows:
            if r.text:
                did = str(r.document_id)
                doc_ocr_map[did] = (doc_ocr_map.get(did, "") + " " + r.text).strip()
        ocr_text = " ".join(r.text for r in rows if r.text)[:2000]
    # Fallback: read PDF directly
    if not ocr_text and docs:
        for doc in docs:
            if doc.file_type == "application/pdf" and doc.minio_path:
                try:
                    import pdfplumber
                    parts = []
                    with pdfplumber.open(doc.minio_path) as pdf:
                        for page in pdf.pages[:10]:
                            t = page.extract_text()
                            if t:
                                parts.append(t)
                    fallback_text = " ".join(parts)[:3000]
                    if fallback_text:
                        doc_ocr_map[str(doc.id)] = fallback_text
                        if not ocr_text:
                            ocr_text = fallback_text[:2000]
                except Exception:
                    pass

    # Predictions
    preds = db.query(Prediction).filter(Prediction.claim_id == claim.id).order_by(Prediction.created_at.desc()).limit(3).all()
    predictions = [{"rejection_score": p.rejection_score, "top_reasons": p.top_reasons, "model_name": p.model_name} for p in preds]

    # Validations — re-run rules live so preview always reflects current data
    parsed = _build_parsed_field_map(pf_rows)
    _codes_for_rules = [{"code": c.code, "code_system": c.code_system, "is_primary": getattr(c, "is_primary", False)} for c in codes]
    _rejection_score = preds[0].rejection_score if preds else None
    _rule_ctx = {"field_map": parsed, "codes": _codes_for_rules, "rejection_score": _rejection_score}
    _rule_results = _run_validation_rules(_rule_ctx) if _run_validation_rules else []
    validations = [{"rule_id": r.rule_id, "rule_name": r.rule_name, "severity": r.severity, "message": r.message, "passed": r.passed} for r in _rule_results]

    icd_list = [{"code": c.code, "description": c.description or "", "confidence": c.confidence, "estimated_cost": getattr(c, "estimated_cost", None)} for c in codes if c.code_system == "ICD10"]
    cpt_list = [{"code": c.code, "description": c.description or "", "confidence": c.confidence, "estimated_cost": getattr(c, "estimated_cost", None)} for c in codes if c.code_system == "CPT"]

    icd_total = sum(x["estimated_cost"] or 0 for x in icd_list)
    cpt_total = sum(x["estimated_cost"] or 0 for x in cpt_list)

    # ── Build expense breakdown from parsed fields ──
    _EXPENSE_FIELDS = {
        "room_charges": "Room Charges",
        "room_charge": "Room Charges",
        "consultation_charges": "Consultation Charges",
        "consultation_fee": "Consultation Charges",
        "pharmacy_charges": "Pharmacy & Medicines",
        "pharmacy_charge": "Pharmacy & Medicines",
        "laboratory_charges": "Laboratory Charges",
        "radiology_charges": "Radiology & Imaging",
        "investigation_charges": "Diagnostics & Investigations",
        "investigation_charge": "Diagnostics & Investigations",
        "surgery_charges": "Surgery Charges",
        "surgery_charge": "Surgery Charges",
        "surgeon_fees": "Surgeon & Professional Fees",
        "anaesthesia_charges": "Anaesthesia Charges",
        "ot_charges": "Operation Theatre Charges",
        "consumables": "Medical & Surgical Consumables",
        "nursing_charges": "Nursing & Support Services",
        "icu_charges": "ICU Charges",
        "ambulance_charges": "Ambulance Charges",
        "misc_charges": "Miscellaneous Charges",
        "isolation_charges": "Isolation Ward Charges",
        "transplant_charges": "Stem Cell / Transplant Charges",
        "chemotherapy_charges": "Chemotherapy & Conditioning",
        "blood_charges": "Blood Products & Bank",
        "physiotherapy_charges": "Physiotherapy Charges",
        "other_charges": "Other Charges",
    }
    expenses: list[dict[str, Any]] = []
    seen_expense_labels: dict[str, float] = {}
    for field_key, val in parsed.items():
        if not val:
            continue
            
        display_label = None
        if field_key in _EXPENSE_FIELDS:
            display_label = _EXPENSE_FIELDS[field_key]
        elif field_key.endswith("_expense"):
            display_label = field_key.replace("_expense", "").replace("_", " ").title()
            
        if display_label:
            try:
                amount = float(val.replace(",", ""))
                if amount > 0 and display_label not in seen_expense_labels:
                    seen_expense_labels[display_label] = amount
                    expenses.append({"category": display_label, "amount": amount})
            except (ValueError, AttributeError):
                pass
    expense_total = sum(e["amount"] for e in expenses)

    gross_total_claimed = 0.0
    gross_total_found = False
    radiology_doc_ids: set[str] = set()
    hospital_bill_subtotals: dict[str, float] = {}
    for d in docs:
        did = str(d.id)
        dtext = doc_ocr_map.get(did, "")
        if not dtext:
            continue
        inferred_type = _infer_document_type(d.file_name or "", dtext)
        if inferred_type == "RADIOLOGY_REPORT":
            radiology_doc_ids.add(did)
        if inferred_type != "HOSPITAL_BILL":
            continue
        if not hospital_bill_subtotals:
            hospital_bill_subtotals = _extract_hospital_bill_subtotals(dtext)
        gross = _extract_gross_total(dtext)
        if gross is not None:
            gross_total_claimed = gross
            gross_total_found = True
            break

    # We no longer override with bill-summary anchored expense categories.
    # The `expense-table-v4` engine is now highly accurate and granular, 
    # capturing all necessary sub-categories directly.

    billed_total = gross_total_claimed if gross_total_found else 0.0
    if not gross_total_found:
        billed_total_str = parsed.get("total_amount", "")
        if billed_total_str:
            try:
                billed_total = float(billed_total_str.replace(",", ""))
            except (ValueError, AttributeError):
                billed_total = 0.0

    reconciliation_warnings: list[str] = []
    if gross_total_found and expense_total > 0:
        diff = abs(billed_total - expense_total)
        margin = billed_total * 0.01
        if diff > margin:
            reconciliation_warnings.append(
                f"Itemized categories total Rs. {expense_total:,.2f} differs from HOSPITAL_BILL GROSS TOTAL Rs. {billed_total:,.2f} by Rs. {diff:,.2f} (>1%)."
            )
    if not gross_total_found:
        reconciliation_warnings.append(
            "HOSPITAL_BILL GROSS TOTAL anchor was not found; billed total fell back to parsed total_amount."
        )

    # ── Scan analyses (MRI / CT / X-Ray / Ultrasound) ──
    scan_rows = db.query(ScanAnalysis).filter(ScanAnalysis.claim_id == claim.id).all()
    scan_analyses = []
    for s in scan_rows:
        if radiology_doc_ids and str(s.document_id) not in radiology_doc_ids:
            continue
        if not radiology_doc_ids:
            # No radiology source document in this claim; suppress imaging insights.
            continue
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

    return {
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
        "ocr_excerpt": ocr_text,
        "documents": [{"file_name": d.file_name, "file_type": d.file_type, "doc_id": str(d.id)} for d in docs],
        "document_texts": {str(d.id): doc_ocr_map.get(str(d.id), "")[:3000] for d in docs},
        "scan_analyses": scan_analyses,
        "identity_review": {
            "excluded_document_ids": [str(i) for i in identity_excluded_doc_ids],
            "manual_review_required": len(identity_warnings) > 0,
            "warnings": identity_warnings,
        },
    }


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


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
    style: str = "modern",
    db: Session = Depends(get_db),
):
    """Generate the IRDA standard reimbursement claim form (Part A + Part B) PDF.

    Two visual styles are supported:

    * ``style=modern`` *(default)* — a polished HTML/CSS rendition with a
      gradient cover page, section cards, and a tabular expense breakdown.
      Print-ready PDF (not interactive).
    * ``style=legacy`` — the original tabular fpdf2 rendition that returns
      an *interactive* AcroForm PDF (every value cell, Yes/No radio and
      checklist box becomes an editable widget).

    Pass ``?blank=1`` to download an empty template with the same layout
    (only policy / patient identifiers retained) for manual filling.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    claim_data = _gather_claim_data_full(db, claim)

    use_modern = style.lower() == "modern" and generate_irda_pdf_modern is not None
    if use_modern:
        try:
            pdf_bytes = bytes(generate_irda_pdf_modern(claim_data, blank=blank))
        except Exception as exc:
            logging.getLogger("submission").exception(
                "Modern IRDA renderer failed, falling back to legacy: %s", exc,
            )
            pdf_bytes = bytes(generate_irda_pdf(claim_data, blank=blank))
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
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/claims/{claim_id}/preview")
def preview_claim_data(claim_id: str, db: Session = Depends(get_db)):
    """Return full structured claim data as JSON for in-app PDF preview before submission."""
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    data = _gather_claim_data_full(db, claim)

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


@router.put("/claims/{claim_id}/fields")
def update_claim_fields(
    claim_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Update parsed fields for a claim.  Body: {"fields": {"patient_name": "...", ...}}
    Upserts rows in parsed_fields table so the PDF and preview reflect edits.
    """
    cid = _parse_uuid(claim_id)
    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    fields = body.get("fields", {})
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided")

    updated = 0
    for field_name, field_value in fields.items():
        existing = db.query(ParsedField).filter(
            ParsedField.claim_id == cid,
            ParsedField.field_name == field_name,
        ).first()
        if existing:
            existing.field_value = str(field_value) if field_value is not None else ""
        else:
            db.add(ParsedField(claim_id=cid, field_name=field_name, field_value=str(field_value) if field_value is not None else ""))
        updated += 1

    db.commit()
    logger.info("Updated %d field(s) for claim %s", updated, str(cid)[:8])
    return {"status": "ok", "updated": updated}


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

    # Record submission with TPA details
    sub = Submission(
        claim_id=cid,
        payer=tpa.name,
        request_payload={**payload, "tpa_id": tpa.code, "tpa_email": tpa.email or ""},
        response_payload={
            "ack": True,
            "reference": f"TPA-{tpa.code.upper()[:8]}-{str(cid)[:8]}",
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

    logger.info("Claim %s sent to TPA '%s' — ref=%s", str(cid)[:8], tpa.name, sub.response_payload["reference"])

    return {
        "status": "success",
        "submission_id": str(sub.id),
        "tpa_name": tpa.name,
        "reference": sub.response_payload["reference"],
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
