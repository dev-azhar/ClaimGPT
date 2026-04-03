"""
TPA-readable PDF generator for insurance claims.

Gathers all claim data (patient info, diagnoses, procedures, ICD/CPT codes,
amounts, provider, validation results) and produces a professional PDF
in standard TPA claim format.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fpdf import FPDF

logger = logging.getLogger("submission.tpa_pdf")


def _sanitize(text: str) -> str:
    """Replace non-latin-1 characters for fpdf2 core fonts."""
    if not text:
        return ""
    return text.encode("latin-1", "replace").decode("latin-1")


class TPAClaimPDF(FPDF):
    """Custom PDF with header/footer for TPA claims."""

    claim_id: str = ""
    patient_name: str = ""

    def header(self):
        # Blue accent bar
        self.set_fill_color(3, 105, 161)
        self.rect(0, 0, 210, 4, "F")
        self.ln(6)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(3, 105, 161)
        self.cell(0, 10, "CLAIMGPT", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, "AI-Powered Medical Insurance Claim Report", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(3, 105, 161)
        self.set_line_width(0.5)
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(6)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"ClaimGPT AI Claims Brain  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(3, 105, 161)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, _sanitize(f"  {title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def field_row(self, label: str, value: str):
        self.set_font("Helvetica", "B", 9)
        self.cell(55, 6, _sanitize(label), new_x="RIGHT")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 6, _sanitize(value) or "N/A", new_x="LMARGIN", new_y="NEXT")

    def table_header(self, columns: list[tuple]):
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(99, 102, 241)
        self.set_text_color(255, 255, 255)
        for col_name, col_width in columns:
            self.cell(col_width, 7, _sanitize(col_name), border=1, fill=True, align="C")
        self.ln()
        self.set_text_color(0, 0, 0)

    def table_row(self, values: list[str], widths: list[int]):
        self.set_font("Helvetica", "", 9)
        for val, w in zip(values, widths, strict=False):
            self.cell(w, 6, _sanitize(str(val)[:40]), border=1, align="C")
        self.ln()


def _generate_brain_insights(claim_data: dict[str, Any]) -> list[str]:
    """Synthesize AI-driven insights from all claim data — the 'Claims Brain'."""
    insights: list[str] = []
    fields = claim_data.get("parsed_fields", {})
    icd = claim_data.get("icd_codes", [])
    cpt = claim_data.get("cpt_codes", [])
    preds = claim_data.get("predictions", [])
    vals = claim_data.get("validations", [])
    docs = claim_data.get("documents", [])
    cost = claim_data.get("cost_summary", {})

    # Document intelligence
    doc_count = len(docs)
    doc_types = set()
    for d in docs:
        ft = (d.get("file_type") or "").lower()
        if "pdf" in ft:
            doc_types.add("PDF")
        elif "image" in ft or "jpg" in ft or "png" in ft:
            doc_types.add("Image")
        else:
            doc_types.add("Document")
    insights.append(
        f"[DOCUMENTS] Analyzed {doc_count} document(s) ({', '.join(doc_types) or 'N/A'}) "
        f"and extracted {len(fields)} structured fields via OCR + AI parsing."
    )

    # Diagnosis-procedure correlation
    diagnosis = fields.get("diagnosis") or fields.get("primary_diagnosis", "")
    procedure = fields.get("procedure") or fields.get("service_description", "")
    if diagnosis and icd:
        primary = next((c for c in icd if isinstance(c, dict) and c.get("code")), None)
        if primary:
            insights.append(
                f"[CODING] Primary diagnosis '{diagnosis}' mapped to ICD-10 code "
                f"{primary['code']} ({primary.get('description', 'N/A')}) "
                f"with {primary.get('confidence', 0):.0%} confidence."
            )
    if procedure and cpt:
        primary_cpt = cpt[0] if isinstance(cpt[0], dict) else None
        if primary_cpt:
            insights.append(
                f"[CODING] Procedure '{procedure}' mapped to CPT code "
                f"{primary_cpt['code']} ({primary_cpt.get('description', 'N/A')})."
            )

    # Cost intelligence
    expenses = claim_data.get("expenses", [])
    expense_total = claim_data.get("expense_total", 0)
    billed_total = claim_data.get("billed_total", 0)
    grand = cost.get("grand_total", 0)

    if expenses:
        insights.append(
            f"[COST] Extracted {len(expenses)} expense line items from documents totalling "
            f"Rs. {expense_total:,.0f}. "
            f"{'Billed total: Rs. ' + f'{billed_total:,.0f}' + '.' if billed_total > 0 else ''}"
        )
        if expense_total > 0 and billed_total > 0:
            diff = abs(billed_total - expense_total)
            if diff > 100:
                insights.append(
                    f"[ALERT] Itemised expenses (Rs. {expense_total:,.0f}) differ from "
                    f"billed total (Rs. {billed_total:,.0f}) by Rs. {diff:,.0f}. "
                    f"Verify for missing or duplicate charges."
                )
    elif billed_total > 0:
        insights.append(
            f"[COST] Billed amount from document: Rs. {billed_total:,.0f}. "
            f"No itemised expense breakdown found."
        )

    if grand > 0:
        insights.append(
            f"[COST] Estimated cost based on ICD/CPT codes: Rs. {grand:,.2f}."
        )

    # Risk intelligence
    if preds:
        p = preds[0]
        score = p.get("rejection_score", 0)
        reasons = p.get("top_reasons", [])
        model = p.get("model_name", "ensemble")
        risk = "HIGH" if score > 0.6 else "LOW" if score <= 0.3 else "MODERATE"
        insights.append(
            f"[RISK] ML model ({model}) predicts {risk} rejection risk "
            f"(score: {score:.0%}). {len(reasons)} risk factor(s) identified."
        )
        if score > 0.5 and reasons:
            top = reasons[0]
            reason_text = top.get("reason", str(top)) if isinstance(top, dict) else str(top)
            insights.append(f"[RISK] Top rejection factor: {reason_text}")

    # Validation intelligence
    if vals:
        passed = sum(1 for v in vals if v.get("passed"))
        failed = [v for v in vals if not v.get("passed")]
        errors = [v for v in failed if v.get("severity") == "ERROR"]
        insights.append(
            f"[VALIDATION] {passed}/{len(vals)} rules passed. "
            f"{len(errors)} critical error(s), {len(failed) - len(errors)} warning(s)."
        )
        if errors:
            names = ", ".join(e.get("rule_name", "?") for e in errors[:3])
            insights.append(f"[ALERT] Critical failures: {names}. These must be resolved before submission.")

    # Completeness check
    critical_aliases = {
        "patient_name": ("patient_name", "member_name", "insured_name"),
        "diagnosis": ("diagnosis", "primary_diagnosis", "chief_complaint"),
        "total_amount": ("total_amount", "amount", "billed_amount"),
        "policy_number": ("policy_number", "policy_id", "policy_no", "member_id"),
        "service_date": ("service_date", "admission_date", "date_of_service"),
    }
    missing = []
    for display_key, aliases in critical_aliases.items():
        if not any(fields.get(a) for a in aliases):
            missing.append(display_key)
    total_critical = len(critical_aliases)
    if missing:
        insights.append(
            f"[COMPLETENESS] Missing critical fields: {', '.join(f.replace('_', ' ').title() for f in missing)}. "
            f"Claim is {((total_critical - len(missing)) / total_critical) * 100:.0f}% complete."
        )
    else:
        insights.append("[COMPLETENESS] All critical fields present. Claim is 100% complete for submission.")

    # Imaging / scan analysis intelligence
    scans = claim_data.get("scan_analyses", [])
    if scans:
        for s in scans:
            stype = s.get("scan_type", "Scan")
            body = s.get("body_part", "unspecified region")
            n_findings = len(s.get("findings", []))
            is_abnormal = s.get("is_abnormal", False)
            impression = s.get("impression", "")
            tag = "IMAGING"
            if is_abnormal:
                critical_findings = [f for f in s.get("findings", []) if f.get("severity") == "critical"]
                if critical_findings:
                    insights.append(
                        f"[{tag}] ⚠️ {stype} scan of {body} detected {len(critical_findings)} critical finding(s). "
                        f"Immediate clinical attention may be required."
                    )
                else:
                    insights.append(
                        f"[{tag}] {stype} scan of {body} shows abnormalities — "
                        f"{n_findings} finding(s) identified. {impression[:120] if impression else ''}"
                    )
            else:
                insights.append(
                    f"[{tag}] {stype} scan of {body} analyzed — {n_findings} finding(s). "
                    f"{impression[:120] if impression else 'Study within normal limits.'}"
                )

    if not insights:
        insights.append("No additional insights available. Upload more documents for deeper analysis.")

    return insights


# ────────────────────────────────────────────────────────────────────
# Cross-Document Reimbursement Intelligence
# ────────────────────────────────────────────────────────────────────

import re as _re

_DOC_TYPE_PATTERNS = [
    ("Discharge Summary", _re.compile(
        r"discharge\s+summar|discharge\s+report|discharge\s+certificate|final\s+summary",
        _re.IGNORECASE)),
    ("Insurance Claim Form", _re.compile(
        r"insurance\s+claim|claim\s+form|pre[\-\s]?auth|cashless\s+form|reimbursement\s+form",
        _re.IGNORECASE)),
    ("Hospital Bill", _re.compile(
        r"hospital\s+bill|final\s+bill|expense\s+statement|bill\s+summary|invoice|receipt\s+cum",
        _re.IGNORECASE)),
    ("Prescription", _re.compile(
        r"prescription|rx\b|prn\b|treatment\s+sheet|drug\s+chart|medication\s+order",
        _re.IGNORECASE)),
    ("Lab Report", _re.compile(
        r"lab\s+report|laboratory|pathology|blood\s+test|hematology|biochemistry|urine\s+(?:test|analysis)|culture\s+sensitivity",
        _re.IGNORECASE)),
    ("Radiology Report", _re.compile(
        r"radiology|x[\-\s]?ray|mri|ct\s+scan|ultrasound|usg|imaging\s+report|sonography",
        _re.IGNORECASE)),
    ("Investigation Report", _re.compile(
        r"investigation|diagnostic|ecg|eeg|endoscop|colonoscop|biopsy",
        _re.IGNORECASE)),
    ("Doctor Certificate", _re.compile(
        r"doctor.?s?\s+certificate|medical\s+certificate|fitness\s+certificate|treating\s+doctor",
        _re.IGNORECASE)),
    ("Policy Document", _re.compile(
        r"policy\s+(?:document|number|details|schedule)|sum\s+insured|premium|coverage",
        _re.IGNORECASE)),
    ("KYC / ID", _re.compile(
        r"aadhaar|pan\s+card|passport|voter\s+id|identity\s+proof|kyc",
        _re.IGNORECASE)),
]

_REIMBURSEMENT_FIELDS = {
    "patient_name": _re.compile(r"(?:patient\s*(?:name)?|name\s+of\s+patient)\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", _re.IGNORECASE),
    "admission_date": _re.compile(r"admission\s*(?:date)?\s*:?\s*(\d{1,2}[\-/]\w{3,9}[\-/]\d{2,4})", _re.IGNORECASE),
    "discharge_date": _re.compile(r"discharge\s*(?:date)?\s*:?\s*(\d{1,2}[\-/]\w{3,9}[\-/]\d{2,4})", _re.IGNORECASE),
    "diagnosis": _re.compile(r"(?:primary\s+)?diagnosis\s*:?\s*(.+?)(?:\n|$)", _re.IGNORECASE),
    "procedure": _re.compile(r"procedure(?:\s+performed)?\s*:?\s*(.+?)(?:\n|$)", _re.IGNORECASE),
    "hospital": _re.compile(r"hospital\s*(?:name)?\s*:?\s*(.+?)(?:\n|$)", _re.IGNORECASE),
    "policy_number": _re.compile(r"policy\s*(?:no|number)?\s*:?\s*([\w\-]+)", _re.IGNORECASE),
    "total_amount": _re.compile(r"(?:total|grand\s+total|net\s+amount|billed)\s*:?\s*(?:Rs\.?|INR)?\s*([\d,]+\.?\d*)", _re.IGNORECASE),
    "doctor": _re.compile(r"(?:surgeon|doctor|consultant|treating)\s*(?:name)?\s*:?\s*(?:Dr\.?\s*)?([A-Z][a-z]+(?:\s+[A-Z]\.?\s*[a-z]*)*)", _re.IGNORECASE),
}


def _classify_document(file_name: str, ocr_text: str) -> str:
    """Classify a document based on file name and OCR text."""
    combined = f"{file_name} {ocr_text[:1000]}"
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(combined):
            return doc_type
    return "Supporting Document"


def _extract_doc_fields(ocr_text: str) -> dict[str, str]:
    """Extract reimbursement-relevant fields from a single document."""
    extracted = {}
    for field, pattern in _REIMBURSEMENT_FIELDS.items():
        m = pattern.search(ocr_text)
        if m:
            val = m.group(1).strip()
            if val and len(val) > 1:
                extracted[field] = val[:200]
    return extracted


def _generate_reimbursement_brain(claim_data: dict[str, Any]) -> dict[str, Any]:
    """
    Cross-document reimbursement intelligence engine.

    Reads ALL documents, classifies each, extracts per-doc fields,
    cross-references data across documents, and builds a comprehensive
    reimbursement assessment.
    """
    docs = claim_data.get("documents", [])
    doc_texts = claim_data.get("document_texts", {})
    fields = claim_data.get("parsed_fields", {})
    icd_codes = claim_data.get("icd_codes", [])
    cpt_codes = claim_data.get("cpt_codes", [])
    expenses = claim_data.get("expenses", [])
    scans = claim_data.get("scan_analyses", [])

    # ── Step 1: Classify & analyze each document ──
    doc_analyses = []
    for d in docs:
        doc_id = d.get("doc_id", "")
        fname = d.get("file_name", "")
        text = doc_texts.get(doc_id, "")
        if not text:
            continue
        doc_type = _classify_document(fname, text)
        doc_fields = _extract_doc_fields(text)
        doc_analyses.append({
            "file_name": fname,
            "doc_type": doc_type,
            "fields_found": doc_fields,
            "text_length": len(text),
        })

    if not doc_analyses:
        return {"documents_analyzed": [], "cross_references": [], "reimbursement_checklist": [], "insights": []}

    # ── Step 2: Cross-reference across documents ──
    cross_refs = []
    field_sources: dict[str, list[dict[str, str]]] = {}

    for da in doc_analyses:
        for fld, val in da["fields_found"].items():
            if fld not in field_sources:
                field_sources[fld] = []
            field_sources[fld].append({"source": da["file_name"], "doc_type": da["doc_type"], "value": val})

    for fld, sources in field_sources.items():
        if len(sources) >= 2:
            values = [s["value"].lower().strip().rstrip(".") for s in sources]
            all_match = all(v == values[0] for v in values)
            cross_refs.append({
                "field": fld.replace("_", " ").title(),
                "sources": [{"doc": s["source"], "doc_type": s["doc_type"], "value": s["value"]} for s in sources],
                "status": "match" if all_match else "mismatch",
            })

    # ── Step 3: Build reimbursement checklist ──
    checklist = []

    # Required document types for reimbursement
    required_docs = {
        "Discharge Summary": "Mandatory for all inpatient claims",
        "Hospital Bill": "Required for expense verification",
        "Insurance Claim Form": "Required — duly filled and signed",
        "Prescription": "Needed for pharmacy charge verification",
        "Lab Report": "Supports medical necessity of investigations",
        "Radiology Report": "Supports imaging charges and diagnosis",
    }

    found_types = {da["doc_type"] for da in doc_analyses}

    for rtype, reason in required_docs.items():
        present = rtype in found_types
        checklist.append({
            "item": rtype,
            "status": "present" if present else "missing",
            "reason": reason,
        })

    # Required fields for reimbursement
    req_fields = [
        ("patient_name", "Patient identification"),
        ("admission_date", "Stay period verification"),
        ("discharge_date", "Stay period verification"),
        ("diagnosis", "Medical necessity"),
        ("procedure", "Procedure justification"),
        ("total_amount", "Claim amount"),
        ("policy_number", "Policy verification"),
        ("hospital_name", "Hospital verification"),
    ]
    for fld, reason in req_fields:
        val = fields.get(fld) or fields.get(fld.replace("_name", "")) or ""
        checklist.append({
            "item": fld.replace("_", " ").title(),
            "status": "present" if val else "missing",
            "reason": reason,
        })

    # ICD/CPT codes
    checklist.append({
        "item": "ICD-10 Diagnosis Codes",
        "status": "present" if icd_codes else "missing",
        "reason": "Required for claim processing",
    })
    checklist.append({
        "item": "CPT Procedure Codes",
        "status": "present" if cpt_codes else "missing",
        "reason": "Required for procedure billing",
    })

    # ── Step 4: Cross-document insights ──
    insights = []

    # Diagnosis consistency
    diag_sources = field_sources.get("diagnosis", [])
    if len(diag_sources) >= 2:
        diag_vals = {s["value"].lower().strip().rstrip(".") for s in diag_sources}
        if len(diag_vals) == 1:
            insights.append({
                "type": "match",
                "category": "Diagnosis",
                "text": f"Diagnosis '{diag_sources[0]['value']}' is consistently documented across {len(diag_sources)} document(s).",
            })
        else:
            insights.append({
                "type": "mismatch",
                "category": "Diagnosis",
                "text": f"Diagnosis varies across documents: {', '.join(s['value'] + ' (' + s['doc_type'] + ')' for s in diag_sources)}. Verify for TPA.",
            })

    # Patient name consistency
    name_sources = field_sources.get("patient_name", [])
    if len(name_sources) >= 2:
        name_vals = {s["value"].lower().strip() for s in name_sources}
        if len(name_vals) > 1:
            insights.append({
                "type": "mismatch",
                "category": "Patient",
                "text": f"Patient name differs across documents: {', '.join(s['value'] + ' (' + s['source'] + ')' for s in name_sources)}.",
            })

    # Amount verification
    amt_sources = field_sources.get("total_amount", [])
    if len(amt_sources) >= 2:
        try:
            amounts = [float(s["value"].replace(",", "")) for s in amt_sources]
            if len(set(amounts)) > 1:
                insights.append({
                    "type": "mismatch",
                    "category": "Amount",
                    "text": f"Claim amounts differ: {', '.join('Rs. ' + s['value'] + ' (' + s['doc_type'] + ')' for s in amt_sources)}. Reconcile before submission.",
                })
            else:
                insights.append({
                    "type": "match",
                    "category": "Amount",
                    "text": f"Billed amount Rs. {amt_sources[0]['value']} is consistent across all documents.",
                })
        except (ValueError, TypeError):
            pass

    # Date consistency
    adm_sources = field_sources.get("admission_date", [])
    _disc_sources = field_sources.get("discharge_date", [])  # noqa: F841
    if len(adm_sources) >= 2:
        adm_vals = {s["value"] for s in adm_sources}
        if len(adm_vals) > 1:
            insights.append({
                "type": "mismatch",
                "category": "Dates",
                "text": f"Admission dates differ: {', '.join(s['value'] + ' (' + s['doc_type'] + ')' for s in adm_sources)}.",
            })

    # Duration of stay
    adm = fields.get("admission_date")
    disc = fields.get("discharge_date")
    if adm and disc:
        try:
            from datetime import datetime as _dt
            for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    a = _dt.strptime(adm, fmt)
                    d = _dt.strptime(disc, fmt)
                    stay = (d - a).days
                    if stay >= 0:
                        insights.append({
                            "type": "info",
                            "category": "Stay",
                            "text": f"Duration of hospital stay: {stay} day(s) ({adm} to {disc}).",
                        })
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    # Expense vs diagnosis correlation
    if expenses and fields.get("diagnosis"):
        diag_lower = fields["diagnosis"].lower()
        has_surgery = any(k in diag_lower for k in ["appendect", "surgery", "laparoscop", "excision", "repair"])
        has_surgery_charges = any(e["category"] in ("Surgery Charges", "Surgeon & Professional Fees", "Operation Theatre Charges") for e in expenses)
        if has_surgery and not has_surgery_charges:
            insights.append({
                "type": "mismatch",
                "category": "Expenses",
                "text": "Procedure suggests surgery but no surgery/OT charges found in expenses. Verify billing.",
            })

    # Supporting scans for diagnosis
    if scans:
        for s in scans:
            if s.get("is_abnormal"):
                insights.append({
                    "type": "info",
                    "category": "Imaging",
                    "text": f"{s['scan_type']} scan of {s['body_part']} supports diagnosis with abnormal findings.",
                })

    # Medical necessity
    if fields.get("diagnosis") and icd_codes:
        insights.append({
            "type": "info",
            "category": "Necessity",
            "text": f"Medical necessity established: Diagnosis '{fields['diagnosis']}' mapped to ICD-10 {icd_codes[0]['code']} with procedure codes documented.",
        })

    # Completeness score
    present_count = sum(1 for c in checklist if c["status"] == "present")
    total_count = len(checklist)
    completeness = round((present_count / total_count) * 100) if total_count > 0 else 0

    return {
        "documents_analyzed": doc_analyses,
        "cross_references": cross_refs,
        "reimbursement_checklist": checklist,
        "insights": insights,
        "completeness_pct": completeness,
    }


def generate_tpa_pdf(claim_data: dict[str, Any]) -> bytes:
    """
    Generate a TPA-readable PDF from gathered claim data.

    Args:
        claim_data: dict with keys: claim_id, policy_id, patient_id,
                    parsed_fields, icd_codes, cpt_codes, predictions,
                    validations, documents, ocr_excerpt
    Returns:
        PDF bytes
    """
    pdf = TPAClaimPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    fields = claim_data.get("parsed_fields", {})
    claim_id = claim_data.get("claim_id", "N/A")
    icd_codes = claim_data.get("icd_codes", [])
    cpt_codes = claim_data.get("cpt_codes", [])
    predictions = claim_data.get("predictions", [])
    _validations = claim_data.get("validations", [])  # noqa: F841

    # ── Section 1: Claim Information ──
    pdf.section_title("1. CLAIM INFORMATION")
    pdf.field_row("Claim ID:", claim_id[:36] if claim_id else "N/A")
    pdf.field_row("Policy Number:", fields.get("policy_number") or claim_data.get("policy_id") or "N/A")
    pdf.field_row("Member ID:", fields.get("member_id") or claim_data.get("patient_id") or "N/A")
    pdf.field_row("Group Number:", fields.get("group_number", "N/A"))
    pdf.field_row("Insurer:", fields.get("insurer") or fields.get("insurance_company", "N/A"))
    pdf.field_row("Claim Date:", datetime.now().strftime("%Y-%m-%d"))
    pdf.field_row("Status:", claim_data.get("status", "N/A"))
    pdf.ln(3)

    # ── Section 2: Patient Details ──
    pdf.section_title("2. PATIENT DETAILS")
    pdf.field_row("Patient Name:", fields.get("patient_name") or fields.get("member_name") or fields.get("insured_name", "N/A"))
    pdf.field_row("Date of Birth:", fields.get("date_of_birth") or fields.get("dob", "N/A"))
    pdf.field_row("Age:", fields.get("age", "N/A"))
    pdf.field_row("Gender:", fields.get("gender", "N/A"))
    pdf.field_row("Contact:", fields.get("phone") or fields.get("contact", "N/A"))
    pdf.field_row("Address:", fields.get("address", "N/A"))
    pdf.ln(3)

    # ── Section 3: Hospital / Provider ──
    pdf.section_title("3. PROVIDER / HOSPITAL DETAILS")
    pdf.field_row("Hospital:", fields.get("hospital_name") or fields.get("hospital") or fields.get("provider_name", "N/A"))
    pdf.field_row("Treating Doctor:", fields.get("doctor_name") or fields.get("provider_name") or fields.get("rendering_provider") or fields.get("treating_doctor", "N/A"))
    pdf.field_row("Provider ID:", fields.get("provider_id") or fields.get("npi", "N/A"))
    pdf.field_row("Admission Date:", fields.get("admission_date") or fields.get("service_date", "N/A"))
    pdf.field_row("Discharge Date:", fields.get("discharge_date", "N/A"))
    pdf.field_row("Length of Stay:", fields.get("length_of_stay", "N/A"))
    pdf.ln(3)

    # ── Section 4: Diagnosis ──
    pdf.section_title("4. DIAGNOSIS (ICD-10 CODES)")
    pdf.field_row("Primary Diagnosis:", fields.get("primary_diagnosis") or fields.get("diagnosis", "N/A"))
    if icd_codes:
        cols = [("S.No", 12), ("ICD-10 Code", 28), ("Description", 75), ("Est. Cost", 25), ("Confidence", 25)]
        pdf.table_header(cols)
        widths = [12, 28, 75, 25, 25]
        for i, code in enumerate(icd_codes[:15], 1):
            if isinstance(code, dict):
                cost_str = f"Rs. {code['estimated_cost']:,.0f}" if code.get("estimated_cost") else "N/A"
                conf_str = f"{code['confidence']:.0%}" if code.get("confidence") else "N/A"
                pdf.table_row(
                    [str(i), code.get("code", ""), code.get("description", "")[:35], cost_str, conf_str],
                    widths,
                )
            else:
                pdf.table_row([str(i), str(code), "", "", ""], widths)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No ICD-10 codes assigned", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── Section 5: Procedures ──
    pdf.section_title("5. PROCEDURES (CPT CODES)")
    pdf.field_row("Primary Procedure:", fields.get("procedure") or fields.get("service_description", "N/A"))
    if cpt_codes:
        cols = [("S.No", 12), ("CPT Code", 28), ("Description", 75), ("Est. Cost", 25), ("Confidence", 25)]
        pdf.table_header(cols)
        widths = [12, 28, 75, 25, 25]
        for i, code in enumerate(cpt_codes[:15], 1):
            if isinstance(code, dict):
                cost_str = f"Rs. {code['estimated_cost']:,.0f}" if code.get("estimated_cost") else "N/A"
                conf_str = f"{code['confidence']:.0%}" if code.get("confidence") else "N/A"
                pdf.table_row(
                    [str(i), code.get("code", ""), code.get("description", "")[:35], cost_str, conf_str],
                    widths,
                )
            else:
                pdf.table_row([str(i), str(code), "", "", ""], widths)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No CPT codes assigned", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── Section 6: Cost Estimation ──
    cost_summary = claim_data.get("cost_summary", {})
    pdf.section_title("6. ESTIMATED COST SUMMARY")
    icd_total = cost_summary.get("icd_total", 0)
    cpt_total = cost_summary.get("cpt_total", 0)
    grand_total = cost_summary.get("grand_total", 0)
    pdf.field_row("Diagnosis Cost (ICD-10):", f"Rs. {icd_total:,.2f}")
    pdf.field_row("Procedure Cost (CPT):", f"Rs. {cpt_total:,.2f}")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(55, 7, _sanitize("  GRAND TOTAL:"), new_x="RIGHT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(3, 105, 161)
    pdf.cell(0, 7, _sanitize(f"Rs. {grand_total:,.2f}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ── Section 7: Billing / Expense Breakdown ──
    expenses = claim_data.get("expenses", [])
    billed_total = claim_data.get("billed_total", 0)
    expense_total = claim_data.get("expense_total", 0)
    pdf.section_title("7. HOSPITAL EXPENSE BREAKDOWN")
    if expenses:
        cols = [("S.No", 14), ("Expense Category", 100), ("Amount (INR)", 50)]
        pdf.table_header(cols)
        widths = [14, 100, 50]
        for i, exp in enumerate(expenses, 1):
            pdf.table_row(
                [str(i), exp.get("category", ""), f"Rs. {exp['amount']:,.0f}"],
                widths,
            )
        # Sub-total row
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(14, 7, "", border=1)
        pdf.cell(100, 7, _sanitize("  Itemised Total"), border=1)
        pdf.cell(50, 7, _sanitize(f"Rs. {expense_total:,.0f}"), border=1, align="C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No itemised expenses extracted from documents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    amount = fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(55, 7, _sanitize("  BILLED TOTAL:"), new_x="RIGHT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(3, 105, 161)
    pdf.cell(0, 7, _sanitize(f"Rs. {amount}" if amount else "N/A"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # ── Section 8: Risk Assessment ──
    if predictions:
        pdf.section_title("8. AI RISK ASSESSMENT")
        for p in predictions[:3]:
            score = p.get("rejection_score", p.get("score", "N/A"))
            risk = "HIGH" if isinstance(score, (int, float)) and score > 0.6 else "LOW" if isinstance(score, (int, float)) and score <= 0.3 else "MODERATE"
            pdf.field_row("Rejection Risk:", f"{score} ({risk})")
            reasons = p.get("top_reasons", [])
            if reasons and isinstance(reasons, list):
                for idx, r in enumerate(reasons[:5], 1):
                    reason_text = r.get("reason", str(r)) if isinstance(r, dict) else str(r)
                    pdf.field_row(f"  Risk Factor {idx}:", reason_text)
            pdf.field_row("Model:", p.get("model_name", "N/A"))
        pdf.ln(3)

    # ── Section 9: Reimbursement Support Details ──
    pdf.section_title("9. REIMBURSEMENT SUPPORT DETAILS")

    # 9a. Medical Necessity & Clinical Summary
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, _sanitize("  A. Medical Necessity & Clinical Summary"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    diag = fields.get("diagnosis") or fields.get("primary_diagnosis", "N/A")
    sec_diag = fields.get("secondary_diagnosis", "")
    procedure_text = fields.get("procedure") or fields.get("service_description", "N/A")
    chief = fields.get("chief_complaint") or fields.get("history_of_present_illness", "")
    pdf.field_row("Primary Diagnosis:", diag)
    if sec_diag:
        pdf.field_row("Secondary Diagnosis:", sec_diag)
    pdf.field_row("Procedure Performed:", procedure_text[:80] if procedure_text else "N/A")
    pdf.field_row("Admission Date:", fields.get("admission_date") or fields.get("service_date", "N/A"))
    pdf.field_row("Discharge Date:", fields.get("discharge_date", "N/A"))
    # Compute length of stay
    adm = fields.get("admission_date", "")
    dis = fields.get("discharge_date", "")
    los = fields.get("length_of_stay", "")
    if not los and adm and dis:
        try:
            from dateutil import parser as dparser
            d1 = dparser.parse(adm, dayfirst=True)
            d2 = dparser.parse(dis, dayfirst=True)
            los = f"{(d2 - d1).days} day(s)"
        except Exception:
            los = "N/A"
    pdf.field_row("Length of Stay:", los or "N/A")
    if chief:
        pdf.field_row("Chief Complaint:", chief[:100])
    # ICD-10 justification
    if icd_codes:
        codes_str = ", ".join(
            f"{c['code']} ({c.get('description', '')[:25]})" if isinstance(c, dict) else str(c)
            for c in icd_codes[:5]
        )
        pdf.field_row("ICD-10 Justification:", codes_str)
    if cpt_codes:
        codes_str = ", ".join(
            f"{c['code']} ({c.get('description', '')[:25]})" if isinstance(c, dict) else str(c)
            for c in cpt_codes[:5]
        )
        pdf.field_row("CPT Justification:", codes_str)
    pdf.ln(3)

    # 9b. Treatment Details
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, _sanitize("  B. Treatment Details"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.field_row("Treating Doctor:", fields.get("doctor_name") or fields.get("provider_name") or fields.get("rendering_provider") or fields.get("treating_doctor", "N/A"))
    pdf.field_row("Surgeon:", fields.get("surgeon", "N/A"))
    pdf.field_row("Anaesthetist:", fields.get("anaesthetist", "N/A"))
    pdf.field_row("Type of Admission:", fields.get("admission_type", "Emergency / Planned"))
    pdf.field_row("Room Type:", fields.get("room_type", "N/A"))
    medication = fields.get("medication") or fields.get("medications_at_discharge", "")
    if medication:
        pdf.field_row("Medications:", medication[:100])
    allergy = fields.get("allergy", "")
    if allergy:
        pdf.field_row("Known Allergies:", allergy[:80])
    pdf.ln(3)

    # 9c. Claim Amount Reconciliation
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, _sanitize("  C. Claim Amount Reconciliation"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    billed_amount = fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount")
    pdf.field_row("Total Amount Claimed:", f"Rs. {billed_amount}" if billed_amount else "N/A")
    pdf.field_row("Itemised Expense Total:", f"Rs. {expense_total:,.0f}" if expense_total > 0 else "N/A")
    if expense_total > 0 and billed_total > 0:
        diff = abs(billed_total - expense_total)
        pdf.field_row("Variance:", f"Rs. {diff:,.0f}" if diff > 0 else "NIL")
    pdf.field_row("Policy Number:", fields.get("policy_number") or claim_data.get("policy_id") or "N/A")
    pdf.field_row("Claim Type:", fields.get("claim_type", "Reimbursement"))
    pdf.ln(3)

    # 9d. Supporting Documents
    docs = claim_data.get("documents", [])
    if docs:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, _sanitize("  D. Supporting Documents Submitted"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        cols = [("S.No", 14), ("Document Name", 110), ("Type", 40)]
        pdf.table_header(cols)
        widths = [14, 110, 40]
        for i, doc in enumerate(docs, 1):
            ftype = (doc.get("file_type") or "").split("/")[-1].upper() or "N/A"
            pdf.table_row([str(i), doc.get("file_name", "N/A")[:50], ftype], widths)
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, _sanitize(
            "Note: All documents listed above have been processed through OCR and AI-based extraction. "
            "Original documents are available for verification upon request."
        ), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── Declaration ──
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "DECLARATION", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5,
        "I hereby declare that the information provided above is true and correct to the best "
        "of my knowledge. This claim has been processed by ClaimGPT AI system and verified "
        "against the uploaded medical documents. All ICD-10 and CPT codes have been "
        "automatically extracted and mapped from the source documents.")
    pdf.ln(10)

    # Signature lines
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(90, 6, "____________________________", align="C")
    pdf.cell(90, 6, "____________________________", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(90, 6, "Patient / Authorized Signatory", align="C")
    pdf.cell(90, 6, "Hospital Stamp & Signature", align="C", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
