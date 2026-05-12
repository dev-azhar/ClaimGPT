from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import re


@dataclass
class Candidate:
    field_name: str
    field_value: str | None
    confidence: float
    extractor_name: str
    bounding_box: Dict[str, Any] | None = None
    source_page: int | None = None
    model_version: str | None = None
    document_id: str | None = None
    doc_type: str | None = None


def _is_obvious_label(val: str) -> bool:
    if not val:
        return True
    s = str(val).strip()
    if not s:
        return True
    # common labels
    labels = {"age", "sex", "address", "patient", "name", "dob", "date"}
    low = s.lower()
    if low in labels:
        return True
    # all-caps short tokens like "AGE", "SEX"
    if s.isupper() and len(s.split()) <= 2:
        return True
    return False


def _validate_patient_name(val: str) -> bool:
    if not val:
        return False
    s = str(val).strip()
    # Reject very short values or obvious labels
    if _is_obvious_label(s):
        return False
    parts = [p for p in re.split(r"\s+", s) if p]
    if len(parts) < 2 or len(parts) > 6:
        return False
    # Reject numeric-only or contains digit tokens like '29'
    if any(re.search(r"\d", p) for p in parts):
        return False
    # Reject when contains medical keywords
    medical_kw = {"mg", "tablet", "medicine", "dose", "diagnosis", "summary"}
    if any(p.lower() in medical_kw for p in parts):
        return False
    # Reject if contains ':' or '-' that indicates label
    if ":" in s or "-" in s and len(parts) <= 2:
        return False
    return True


def resolve(candidates: List[Candidate]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Resolve candidates into chosen fields with provenance.

    Returns (resolved_fields, provenance_map)
    - resolved_fields: list of dicts with chosen field data (field_name, field_value, confidence, extractor_name, bounding_box, source_page, model_version, document_id, doc_type)
    - provenance_map: mapping field_name -> {chosen:..., rejected:[...]}
    """
    grouped: Dict[str, List[Candidate]] = {}
    for c in candidates:
        grouped.setdefault(c.field_name, []).append(c)

    resolved: List[Dict[str, Any]] = []
    provenance: Dict[str, Any] = {}

    for field, group in grouped.items():
        # Sort by confidence desc, then extractor preference (already baked into confidence)
        group_sorted = sorted(group, key=lambda x: (x.confidence), reverse=True)

        chosen = None
        rejected = []

        for cand in group_sorted:
            # Field-specific validators
            reason = None
            accept = True
            if field == "patient_name":
                if not _validate_patient_name(cand.field_value or ""):
                    accept = False
                    reason = "failed_patient_name_validation"
            else:
                if _is_obvious_label(cand.field_value or ""):
                    accept = False
                    reason = "obvious_label"

            if accept and not chosen:
                chosen = cand
            else:
                rejected.append({
                    "extractor": cand.extractor_name,
                    "model_version": cand.model_version,
                    "confidence": cand.confidence,
                    "value": cand.field_value,
                    "reason": reason,
                })

        if chosen:
            resolved.append({
                "field_name": chosen.field_name,
                "field_value": chosen.field_value,
                "confidence": chosen.confidence,
                "extractor": chosen.extractor_name,
                "bounding_box": chosen.bounding_box,
                "source_page": chosen.source_page,
                "model_version": chosen.model_version,
                "document_id": chosen.document_id,
                "doc_type": chosen.doc_type,
            })
            provenance[field] = {
                "chosen": {
                    "extractor": chosen.extractor_name,
                    "model_version": chosen.model_version,
                    "confidence": chosen.confidence,
                    "value": chosen.field_value,
                },
                "rejected": rejected,
            }
        else:
            # no candidate accepted: include highest-confidence as chosen but mark low confidence
            top = group_sorted[0]
            resolved.append({
                "field_name": top.field_name,
                "field_value": top.field_value,
                "confidence": top.confidence,
                "extractor": top.extractor_name,
                "bounding_box": top.bounding_box,
                "source_page": top.source_page,
                "model_version": top.model_version,
                "document_id": top.document_id,
                "doc_type": top.doc_type,
            })
            provenance[field] = {
                "chosen": {
                    "extractor": top.extractor_name,
                    "model_version": top.model_version,
                    "confidence": top.confidence,
                    "value": top.field_value,
                    "note": "no_candidate_passed_validators",
                },
                "rejected": [
                    {
                        "extractor": c.extractor_name,
                        "model_version": c.model_version,
                        "confidence": c.confidence,
                        "value": c.field_value,
                        "reason": "validator_rejected",
                    }
                    for c in group_sorted[1:]
                ],
            }

    return resolved, provenance
