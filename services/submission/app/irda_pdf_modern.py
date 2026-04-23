"""
Modern HTML/CSS-based renderer for the IRDA Standard Health Insurance
Claim Form (Part A + Part B).

Uses Jinja2 templates + WeasyPrint to produce a polished, print-ready PDF
that follows the IRDAI section/field structure but with a contemporary
visual design (cover page, gradient banners, section cards, tabular
expense breakdown, AI-filled provenance highlighting, paged headers /
footers, page-numbering).

Public entry-point: ``generate_irda_pdf_modern(claim_data, blank=False)``
returning ``bytes`` — drop-in compatible with the legacy ``generate_irda_pdf``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger("submission.irda_pdf_modern")

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Lazy-init Jinja env so import-time is cheap.
_env: Environment | None = None


def _jinja_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


# ─── helpers ────────────────────────────────────────────────────────────
def _g(fields: dict[str, Any], *keys: str, default: str = "") -> str:
    """First non-empty value among the candidate field keys, stringified."""
    for k in keys:
        v = fields.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default


def _money(val: Any) -> str:
    """Format an amount as Indian-grouped rupees, no symbol."""
    if val in (None, ""):
        return ""
    try:
        n = float(str(val).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return str(val)
    # Indian grouping (xx,xx,xxx)
    neg = n < 0
    n = abs(n)
    int_part = int(round(n))
    s = str(int_part)
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        out = f"{head},{tail}"
    return f"-{out}" if neg else out


def _money_full(val: Any) -> str:
    s = _money(val)
    return f"₹ {s}" if s else ""


def _field(label: str, value: Any, *, ai: bool = False, required: bool = False, span: int | str | None = None) -> dict[str, Any]:
    return {
        "k": label,
        "v": "" if value in (None, "") else str(value),
        "ai": ai and bool(value),  # only highlight if actually filled by AI
        "required": required,
        "span": span,
    }


# ─── document checklist (mirrors the legacy renderer) ───────────────────
_DOC_CHECKLIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Duly completed claim form", ("claim_form",)),
    ("Original main hospital bill", ("final_bill", "hospital_bill", "bill")),
    ("Itemised hospital bill / break-up", ("itemised_bill", "bill_breakup")),
    ("Original payment receipts", ("payment_receipt", "receipt")),
    ("Discharge / Death summary", ("discharge_summary", "death_summary")),
    ("Investigation reports", ("investigation_report", "lab_report", "diagnostic_report")),
    ("Pharmacy bills", ("pharmacy_bill", "medicine_bill")),
    ("Treating doctor's prescription", ("prescription",)),
    ("Indoor case papers", ("case_papers", "ipd_papers")),
    ("KYC documents (PAN / Aadhaar)", ("kyc", "pan_card", "aadhaar")),
    ("Cancelled cheque (NEFT)", ("cancelled_cheque", "neft_cheque")),
    ("FIR / MLC report (if applicable)", ("fir", "mlc")),
    ("Implant invoice / sticker", ("implant_invoice", "implant_sticker")),
    ("Pre-authorisation letter (if cashless)", ("pre_auth", "preauth_letter")),
)


def _build_checklist(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present = set()
    for d in documents or []:
        ftype = (d.get("file_type") or "").lower()
        fname = (d.get("file_name") or "").lower()
        for token in ("bill", "discharge", "prescription", "report", "cheque",
                       "pan", "aadhaar", "kyc", "receipt", "preauth", "implant",
                       "fir", "mlc", "case", "claim_form"):
            if token in ftype or token in fname:
                present.add(token)
    out = []
    for label, tokens in _DOC_CHECKLIST:
        checked = any(any(t in p or p in t for p in present) for t in tokens)
        out.append({"label": label, "checked": checked})
    return out


# ─── expense head mapping (subset of TPA) ───────────────────────────────
_EXPENSE_FIELDS: tuple[tuple[str, str], ...] = (
    ("room_charges", "Room / Boarding Charges"),
    ("nursing_charges", "Nursing & Support"),
    ("icu_charges", "ICU Charges"),
    ("consultation_charges", "Consultation Charges"),
    ("surgeon_fees", "Surgeon & Professional Fees"),
    ("anaesthesia_charges", "Anaesthesia Charges"),
    ("ot_charges", "Operation Theatre"),
    ("surgery_charges", "Surgery Charges"),
    ("investigation_charges", "Diagnostics & Investigations"),
    ("pharmacy_charges", "Pharmacy & Medicines"),
    ("consumables", "Medical & Surgical Consumables"),
    ("implant_charges", "Implants / Prosthesis"),
    ("ambulance_charges", "Ambulance"),
    ("misc_charges", "Miscellaneous"),
)


def _build_expenses(fields: dict[str, Any]) -> tuple[list[dict[str, str]], float]:
    rows = []
    total = 0.0
    for key, label in _EXPENSE_FIELDS:
        # Try canonical and a couple of common aliases.
        for k in (key, key.rstrip("s"), key.replace("_charges", "_charge")):
            v = fields.get(k)
            if v not in (None, ""):
                try:
                    n = float(str(v).replace(",", "").replace("₹", "").strip())
                except (TypeError, ValueError):
                    n = 0.0
                if n > 0:
                    rows.append({"label": label, "amount": _money(n)})
                    total += n
                break
    return rows, total


# ─── section field-builders ─────────────────────────────────────────────
def _build_sections(fields: dict[str, Any], blank: bool) -> dict[str, Any]:
    ai = not blank  # tag every value-bearing field as "AI-filled" when not blank

    return {
        "a": {
            "title": "Insurer / TPA Details",
            "fields": [
                _field("Name of Insurance Company", _g(fields, "insurer", "insurance_company"), ai=ai, required=True),
                _field("TPA Name", _g(fields, "tpa_name", "tpa"), ai=ai),
                _field("Policy / Health Card No.", _g(fields, "policy_number", "policy_no", "policy_id"), ai=ai, required=True),
                _field("Member ID / UHID", _g(fields, "uhid", "member_id"), ai=ai),
            ],
        },
        "b": {
            "title": "Insured / Policyholder",
            "fields": [
                _field("Name of Insured", _g(fields, "policyholder_name", "insured_name"), ai=ai, required=True),
                _field("Policy Period (From)", _g(fields, "policy_start_date", "policy_from"), ai=ai),
                _field("Policy Period (To)", _g(fields, "policy_end_date", "policy_to"), ai=ai),
                _field("Sum Insured", _money_full(_g(fields, "sum_insured")), ai=ai),
                _field("Cumulative Bonus", _money_full(_g(fields, "cumulative_bonus")), ai=ai),
                _field("Contact Phone", _g(fields, "policyholder_phone", "phone", "mobile"), ai=ai),
                _field("Email", _g(fields, "policyholder_email", "email"), ai=ai),
                _field("Address", _g(fields, "policyholder_address", "address"), ai=ai, span="full"),
            ],
        },
        "c": {
            "title": "Patient Details",
            "fields": [
                _field("Patient Name", _g(fields, "patient_name", "member_name"), ai=ai, required=True),
                _field("Date of Birth", _g(fields, "patient_dob", "dob"), ai=ai),
                _field("Gender", _g(fields, "patient_gender", "gender"), ai=ai),
                _field("Relationship to Insured", _g(fields, "relationship", "patient_relationship"), ai=ai),
                _field("Occupation", _g(fields, "patient_occupation", "occupation"), ai=ai),
                _field("PAN", _g(fields, "patient_pan", "pan"), ai=ai),
            ],
        },
        "d": {
            "title": "Hospitalisation Details",
            "fields": [
                _field("Hospital Name", _g(fields, "hospital_name"), ai=ai, required=True),
                _field("Hospital City / State", _g(fields, "hospital_city"), ai=ai),
                _field("Hospital Phone", _g(fields, "hospital_phone"), ai=ai),
                _field("Date of Admission", _g(fields, "admission_date", "date_of_admission"), ai=ai, required=True),
                _field("Time of Admission", _g(fields, "admission_time"), ai=ai),
                _field("Date of Discharge", _g(fields, "discharge_date", "date_of_discharge"), ai=ai, required=True),
                _field("Time of Discharge", _g(fields, "discharge_time"), ai=ai),
                _field("Length of Stay (Days)", _g(fields, "length_of_stay", "los_days"), ai=ai),
                _field("Room Category", _g(fields, "room_category", "room_type"), ai=ai),
            ],
            "choices": [
                {"label": "Was hospitalisation due to an injury / accident?",
                 "value": (_g(fields, "is_accident", "injury_yn") or "").upper() if _g(fields, "is_accident", "injury_yn") else ""},
                {"label": "Was hospitalisation due to maternity?",
                 "value": (_g(fields, "is_maternity") or "").upper() if _g(fields, "is_maternity") else ""},
                {"label": "Did the patient undergo any surgical procedure?",
                 "value": (_g(fields, "is_surgery") or "").upper() if _g(fields, "is_surgery") else ""},
            ],
        },
        "f": {
            "title": "Bank Details for NEFT Payment",
            "fields": [
                _field("Account Holder Name", _g(fields, "account_holder", "bank_account_name"), ai=ai),
                _field("Bank Name", _g(fields, "bank_name"), ai=ai),
                _field("Branch", _g(fields, "bank_branch"), ai=ai),
                _field("Account Number", _g(fields, "account_number", "bank_account_number"), ai=ai),
                _field("IFSC Code", _g(fields, "ifsc", "ifsc_code"), ai=ai),
                _field("MICR Code", _g(fields, "micr", "micr_code"), ai=ai),
                _field("PAN of Account Holder", _g(fields, "account_pan", "pan"), ai=ai),
            ],
        },
        "h_hospital": {
            "title": "Hospital Identification",
            "fields": [
                _field("Hospital Name", _g(fields, "hospital_name"), ai=ai, required=True),
                _field("Hospital Registration No.", _g(fields, "hospital_registration_no"), ai=ai),
                _field("Address", _g(fields, "hospital_address"), ai=ai, span="full"),
                _field("Phone", _g(fields, "hospital_phone"), ai=ai),
                _field("Email", _g(fields, "hospital_email"), ai=ai),
            ],
        },
        "h_clinical": {
            "title": "Patient Clinical Details",
            "fields": [
                _field("Treating Doctor", _g(fields, "treating_doctor", "doctor_name"), ai=ai),
                _field("Doctor Registration No.", _g(fields, "doctor_registration_no"), ai=ai),
                _field("Department / Speciality", _g(fields, "department", "speciality"), ai=ai),
                _field("Provisional Diagnosis", _g(fields, "provisional_diagnosis"), ai=ai, span="full"),
                _field("Final Diagnosis", _g(fields, "final_diagnosis", "diagnosis"), ai=ai, span="full"),
                _field("Surgery / Procedure Performed", _g(fields, "procedure_performed", "surgery_performed"), ai=ai, span="full"),
                _field("Past History", _g(fields, "past_history", "medical_history"), ai=ai, span="full"),
            ],
        },
    }


# ─── public entry-point ─────────────────────────────────────────────────
def generate_irda_pdf_modern(claim_data: dict[str, Any], blank: bool = False) -> bytes:
    """Render the modern HTML/CSS-based IRDA claim form to PDF bytes."""
    # Lazy import so plain-text test runs don't need WeasyPrint.
    from weasyprint import HTML  # type: ignore

    fields_in: dict[str, Any] = dict(claim_data.get("parsed_fields", {}) or {})
    icd_in = claim_data.get("icd_codes", []) or []
    cpt_in = claim_data.get("cpt_codes", []) or []
    docs = claim_data.get("documents", []) or []

    if blank:
        keep = {"policy_number", "policyholder_name", "patient_name", "insurer", "hospital_name"}
        fields_in = {k: (v if k in keep else "") for k, v in fields_in.items()}
        icd_in, cpt_in = [], []
        docs = []

    icd_codes = [c if isinstance(c, dict) else {"code": str(c), "description": "", "confidence": None} for c in icd_in]
    cpt_codes = [c if isinstance(c, dict) else {"code": str(c), "description": "", "confidence": None} for c in cpt_in]

    expenses, total = _build_expenses(fields_in)
    # Allow an explicit total to override the sum if present.
    explicit_total = fields_in.get("total_claim_amount") or fields_in.get("total_amount")
    if explicit_total:
        try:
            total = float(str(explicit_total).replace(",", "").replace("₹", "").strip())
        except (TypeError, ValueError):
            pass

    summary = {
        "patient_name": _g(fields_in, "patient_name", "member_name", "insured_name"),
        "policy_number": _g(fields_in, "policy_number", "policy_no", "policy_id"),
        "hospital_name": _g(fields_in, "hospital_name"),
        "total_claimed": _money_full(total) if total else _money_full(explicit_total),
        "admission_date": _g(fields_in, "admission_date", "date_of_admission"),
        "discharge_date": _g(fields_in, "discharge_date", "date_of_discharge"),
        "doc_id": str(uuid.uuid4())[:8].upper(),
    }

    ctx = {
        "blank": blank,
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        "summary": summary,
        "sections": _build_sections(fields_in, blank=blank),
        "checklist": _build_checklist(docs),
        "icd_codes": icd_codes,
        "cpt_codes": cpt_codes,
        "expenses": expenses,
        "total_claimed_str": _money(total) if total else "—",
    }

    try:
        html_str = _jinja_env().get_template("irda_form.html").render(**ctx)
    except Exception as exc:
        logger.exception("IRDA modern template render failed: %s", exc)
        raise

    try:
        pdf_bytes = HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf()
    except Exception as exc:
        logger.exception("WeasyPrint render failed: %s", exc)
        raise

    return pdf_bytes
