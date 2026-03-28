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
from .models import Claim, ParsedField, MedicalCode, Submission, Document, OcrResult, Prediction, Validation, ScanAnalysis
from .schemas import SubmissionOut, SubmissionDetailOut, SubmitRequest
from .adapters import get_adapter
from .tpa_pdf import generate_tpa_pdf, _generate_brain_insights, _generate_reimbursement_brain

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

    # Validations
    vals = db.query(Validation).filter(Validation.claim_id == claim.id).all()
    validations = [{"rule_id": v.rule_id, "rule_name": v.rule_name, "severity": v.severity, "message": v.message, "passed": str(v.passed).lower() in ("true", "1", "t")} for v in vals]

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
    parsed = {r.field_name: r.field_value for r in pf_rows}
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
        "patient_name": fields.get("patient_name", "N/A"),
        "age": fields.get("age", "N/A"),
        "gender": fields.get("gender", "N/A"),
        "hospital": fields.get("hospital_name", fields.get("hospital", "N/A")),
        "doctor": fields.get("doctor_name", fields.get("provider_name", "N/A")),
        "admission_date": fields.get("admission_date", "N/A"),
        "discharge_date": fields.get("discharge_date", "N/A"),
        "diagnosis": fields.get("diagnosis", fields.get("chief_complaint", "N/A")),
        "total_amount": fields.get("total_amount", "N/A"),
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


# ── Include router (standalone mode) ──
app.include_router(router)
