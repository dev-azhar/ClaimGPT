from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, engine, check_db_health
from .models import Claim, ParsedField, MedicalCode, Submission, Document, OcrResult, Prediction, Validation, ScanAnalysis, TpaProvider
from .schemas import SubmissionOut, SubmissionDetailOut, SubmitRequest
from .adapters import get_adapter
from .tpa_pdf import generate_tpa_pdf, _generate_brain_insights, _generate_reimbursement_brain

# Import rules engine for live re-validation in preview
from services.validator.app.rules import run_rules as _run_validation_rules

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
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from libs.observability.tracing import init_tracing, instrument_fastapi
    from libs.observability.metrics import init_metrics, PrometheusMiddleware, metrics_endpoint
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


# ------------------------------------------------------------------ helpers

def _gather_claim_data(db: Session, claim: Claim) -> Dict[str, Any]:
    """Collect all data needed for submission payload."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()

    return {
        "claim_id": str(claim.id),
        "policy_id": claim.policy_id,
        "patient_id": claim.patient_id,
        "parsed_fields": {r.field_name: r.field_value for r in pf_rows},
        "icd_codes": [c.code for c in codes if c.code_system == "ICD10"],
        "cpt_codes": [c.code for c in codes if c.code_system == "CPT"],
    }


def _gather_claim_data_full(db: Session, claim: Claim) -> Dict[str, Any]:
    """Collect all data for TPA PDF generation (richer than submission)."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim.id).all()
    docs = db.query(Document).filter(Document.claim_id == claim.id).all()

    # OCR text
    doc_ids = [d.id for d in docs]
    ocr_text = ""
    doc_ocr_map: Dict[str, str] = {}  # doc_id -> full OCR text
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
    parsed = {r.field_name: r.field_value for r in pf_rows}
    _codes_for_rules = [{"code": c.code, "code_system": c.code_system, "is_primary": getattr(c, "is_primary", False)} for c in codes]
    _rejection_score = preds[0].rejection_score if preds else None
    _rule_ctx = {"field_map": parsed, "codes": _codes_for_rules, "rejection_score": _rejection_score}
    _rule_results = _run_validation_rules(_rule_ctx)
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
        "other_charges": "Other Charges",
    }
    expenses: List[Dict[str, Any]] = []
    seen_expense_labels: Dict[str, float] = {}
    for field_key, display_label in _EXPENSE_FIELDS.items():
        val = parsed.get(field_key)
        if val:
            try:
                amount = float(val.replace(",", ""))
                if amount > 0 and display_label not in seen_expense_labels:
                    seen_expense_labels[display_label] = amount
                    expenses.append({"category": display_label, "amount": amount})
            except (ValueError, AttributeError):
                pass
    expense_total = sum(e["amount"] for e in expenses)
    billed_total_str = parsed.get("total_amount", "")
    billed_total = 0.0
    if billed_total_str:
        try:
            billed_total = float(billed_total_str.replace(",", ""))
        except (ValueError, AttributeError):
            pass

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
            "grand_total": round(icd_total + cpt_total, 2),
        },
        "expenses": expenses,
        "expense_total": round(expense_total, 2),
        "billed_total": round(billed_total, 2),
        "predictions": predictions,
        "validations": validations,
        "ocr_excerpt": ocr_text,
        "documents": [{"file_name": d.file_name, "file_type": d.file_type, "doc_id": str(d.id)} for d in docs],
        "document_texts": {str(d.id): doc_ocr_map.get(str(d.id), "")[:3000] for d in docs},
        "scan_analyses": scan_analyses,
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
    from sqlalchemy import text, inspect
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
    rows = db.query(TpaProvider).filter(TpaProvider.is_active == True).order_by(TpaProvider.name).all()
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
        "total_amount": fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount", "N/A"),
        "icd_count": len(data.get("icd_codes", [])),
        "cpt_count": len(data.get("cpt_codes", [])),
        "risk_score": data["predictions"][0]["rejection_score"] if data.get("predictions") else None,
        "validation_passed": sum(1 for v in data.get("validations", []) if v.get("passed")),
        "validation_total": len(data.get("validations", [])),
    }

    # AI Brain insights — synthesized intelligence from all documents
    data["brain_insights"] = _generate_brain_insights(data)

    # Cross-document reimbursement intelligence
    data["reimbursement_brain"] = _generate_reimbursement_brain(data)

    return data


@router.post("/claims/{claim_id}/code-feedback")
def submit_code_feedback(claim_id: str, db: Session = Depends(get_db), body: dict = {}):
    """
    Submit feedback on medical code suggestions for reinforcement learning.
    Body: {"code": "I21.9", "action": "accept|reject|correct", "corrected_code": "I21.3"}
    """
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
    tpa = db.query(TpaProvider).filter(TpaProvider.code == tpa_id, TpaProvider.is_active == True).first()
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


# ── Include router (standalone mode) ──
app.include_router(router)
