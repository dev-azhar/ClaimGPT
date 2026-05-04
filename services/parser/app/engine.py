"""
Advanced document parsing engine — deep structured extraction for medical claims.

Strategy:
  1. **LayoutLMv3** (microsoft/layoutlmv3-base) for structured field extraction
     using token classification on document images + OCR text.
  2. **Advanced heuristic** fallback with 40+ regex patterns covering:
     - Patient demographics (name, DOB, gender, age, address, phone, email)
     - Insurance details (policy, member ID, group, insurer, TPA)
     - Clinical data (diagnosis, ICD-10, procedures, CPT, medications, allergies)
     - Billing (line items, totals, dates of service, room charges)
     - Provider/facility info (hospital, doctor, registration/discharge dates)
     - Discharge summary sections (chief complaint, history, findings, plan)
  3. **Smart table parsing** with header detection and column alignment.
  4. **Amount normalization** (INR/USD, commas, decimals).
  5. **Section detection** for discharge summaries and medical reports.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List, Dict
from urllib import error as urlerror
from urllib import request as urlrequest
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

## Local LLM import removed
from .config import settings

logger = logging.getLogger("parser.engine")


class DocumentType(str, Enum):
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_INVOICE = "PHARMACY_INVOICE"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    UNKNOWN = "UNKNOWN"


@dataclass
class PageObject:
    page_number: int
    document_id: Optional[str]
    raw_text: str
    detected_tables: List[Dict[str, Any]] = field(default_factory=list)
    coordinates: List[Dict[str, Any]] = field(default_factory=list)
    document_type: str = DocumentType.UNKNOWN.value

# ------------------------------------------------------------------
# Lazy-loaded model singleton
# ------------------------------------------------------------------
_model = None
_processor = None
_tokenizer = None
_model_version: str | None = None
_model_load_attempted = False
_llm_unavailable_logged = False


def _load_model() -> bool:
    """Attempt to load LayoutLMv3 model + processor.  Returns True on success."""
    global _model, _processor, _tokenizer, _model_version, _model_load_attempted
    if _model_load_attempted:
        return _model is not None
    _model_load_attempted = True

    try:
        import torch  # noqa: F401
        from transformers import (
            LayoutLMv3ForTokenClassification,
            LayoutLMv3Processor,
            LayoutLMv3TokenizerFast,
        )

        model_id = settings.layoutlm_model
        logger.info("Loading LayoutLMv3 model: %s", model_id)

        _tokenizer = LayoutLMv3TokenizerFast.from_pretrained(model_id)
        _processor = LayoutLMv3Processor.from_pretrained(
            model_id, apply_ocr=False, tokenizer=_tokenizer,
        )
        _model = LayoutLMv3ForTokenClassification.from_pretrained(model_id)
        _model.eval()
        _model_version = model_id

        n_labels = _model.config.num_labels
        logger.info(
            "LayoutLMv3 loaded — %d token-classification labels, device=cpu",
            n_labels,
        )
        return True

    except ImportError:
        logger.warning(
            "transformers / torch not installed — will use heuristic fallback"
        )
        return False
    except Exception:
        logger.warning(
            "Could not load LayoutLMv3 model '%s' — will use heuristic fallback",
            settings.layoutlm_model,
            exc_info=True,
        )
        return False


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class FieldResult:
    field_name: str
    field_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    source_page: int | None = None
    model_version: str | None = None
    document_id: str | None = None
    doc_type: str | None = None


@dataclass
class ParseOutput:
    fields: list[FieldResult] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    page_objects: list[dict[str, Any]] = field(default_factory=list)
    document_boundaries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    model_version: str | None = None
    used_fallback: bool = False


class BillingLineItem(BaseModel):
    description: str
    category: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class StructuredClaimExtraction(BaseModel):
    patient_name: Optional[str] = None
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    age: Optional[int] = None
    hospital_name: Optional[str] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    primary_diagnosis: Optional[str] = None
    secondary_diagnosis: Optional[str] = None
    procedures: list[str] = Field(default_factory=list)
    treating_doctor: Optional[str] = None
    claimed_total: Optional[float] = None
    bill_line_items: list[BillingLineItem] = Field(default_factory=list)
    notes: Optional[str] = None
    confidence: str = "HIGH"

def _merge_structured_extractions(
    base: StructuredClaimExtraction | None,
    incoming: StructuredClaimExtraction,
) -> StructuredClaimExtraction:
    """Merge partial structured outputs from multiple OCR chunks/documents."""
    if base is None:
        return incoming

    scalar_fields = [
        "patient_name", "member_id", "policy_number", "age", "hospital_name",
        "admission_date", "discharge_date", "primary_diagnosis", "secondary_diagnosis",
        "treating_doctor", "claimed_total", "notes",
    ]
    for fld in scalar_fields:
        current_val = getattr(base, fld)
        incoming_val = getattr(incoming, fld)
        if current_val is None and incoming_val is not None:
            setattr(base, fld, incoming_val)

    seen_proc = {p.strip().lower() for p in base.procedures if p and p.strip()}
    for proc in incoming.procedures:
        key = (proc or "").strip().lower()
        if key and key not in seen_proc:
            base.procedures.append(proc)
            seen_proc.add(key)

    seen_items: set[tuple[str, float]] = set()
    merged_items: list[BillingLineItem] = []
    for item in list(base.bill_line_items) + list(incoming.bill_line_items):
        desc = (item.description or "").strip()
        amt = _safe_float(item.amount) or 0.0
        key = (desc.lower(), round(amt, 2))
        if not desc or key in seen_items:
            continue
        seen_items.add(key)
        merged_items.append(item)
    base.bill_line_items = merged_items

    # Conservative confidence merge.
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    base_score = order.get((base.confidence or "MEDIUM").upper(), 1)
    in_score = order.get((incoming.confidence or "MEDIUM").upper(), 1)
    base.confidence = ["LOW", "MEDIUM", "HIGH"][min(base_score, in_score)]
    return base


class DischargeSummarySchema(BaseModel):
    patient_name: Optional[str] = Field(default=None, pattern=r"^[A-Za-z .'-]{3,120}$")
    date_of_birth: Optional[str] = Field(default=None, pattern=r"^[0-3]?\d[-/\. ][A-Za-z0-9]{2,10}[-/\. ]\d{2,4}$")
    age: Optional[int] = Field(default=None, ge=0, le=120)
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None


class HospitalBillSchema(BaseModel):
    total_amount: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
    room_charges: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
    consultation_charges: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
    investigation_charges: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
HospitalBillSchema.model_rebuild()

class PharmacyInvoiceSchema(BaseModel):
    pharmacy_charges: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
    total_amount: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")


class LabReportSchema(BaseModel):
    investigation_charges: Optional[str] = Field(default=None, pattern=r"^\d+(?:\.\d{2})?$")
    icd_code: Optional[str] = Field(default=None, pattern=r"^[A-TV-Z]\d{2}(?:\.\d{1,4})?$")


_DOC_KEYWORDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.DISCHARGE_SUMMARY: (
        "discharge summary", "history of presenting illness", "condition at discharge",
        "medications at discharge", "final diagnosis",
    ),
    DocumentType.LAB_REPORT: (
        "laboratory", "investigation report", "haematology", "biomarkers",
        "test name", "reference range",
    ),
    DocumentType.PHARMACY_INVOICE: (
        "pharmacy invoice", "in-house pharmacy", "drug name", "dispense", "medicine cost",
    ),
    DocumentType.HOSPITAL_BILL: (
        "medical insurance claim form", "hospitalization details", "date of admission",
        "date of discharge", "claim amount requested", "hospital expense breakdown",
        "itemized inpatient hospital bill", "bill summary", "gross total", "room & boarding",
        "procedure / surgical charges", "amount payable",
        # Expense table continuation cues — prevents billing pages from being
        # misclassified as LAB_REPORT when they contain words like "laboratory".
        "total amount", "claim amount", "amount exceeding", "expense category",
        "billed total", "itemised total", "consumables", "miscellaneous",
        "nursing", "surgery charges", "ot charges", "anaesthesia",
    ),
}


# Strict field allow-list per routed document type.
_DOC_TYPE_FIELD_ALLOWLIST: dict[str, set[str]] = {
    DocumentType.DISCHARGE_SUMMARY.value: {
        "patient_name", "date_of_birth", "age", "gender", "address", "phone", "email",
        "patient_id", "policy_number", "claim_number", "member_id", "group_number", "insurer",
        "diagnosis", "secondary_diagnosis", "icd_code", "procedure", "cpt_code", "medication",
        "allergy", "chief_complaint", "history_of_present_illness", "hospital_name", "doctor_name",
        "registration_number", "admission_date", "discharge_date", "service_date", "blood_pressure",
        "pulse", "temperature", "spo2",
    },
    DocumentType.HOSPITAL_BILL.value: {
        "patient_name", "date_of_birth", "age", "gender", "address", "phone", "email",
        "policy_number", "claim_number", "member_id", "patient_id", "insurer", "hospital_name", "doctor_name",
        "diagnosis", "secondary_diagnosis", "icd_code", "procedure", "cpt_code",
        "admission_date", "discharge_date", "service_date", "total_amount", "room_charges",
        "consultation_charges", "pharmacy_charges", "investigation_charges", "surgery_charges",
        "surgeon_fees", "anaesthesia_charges", "ot_charges", "consumables", "nursing_charges",
        "icu_charges", "ambulance_charges", "misc_charges", "other_charges",
        "laboratory_charges", "radiology_charges", "isolation_charges",
        "transplant_charges", "chemotherapy_charges", "blood_charges",
    },
    DocumentType.PHARMACY_INVOICE.value: {
        "patient_name", "date_of_birth", "age", "gender", "hospital_name",
        "policy_number", "member_id", "patient_id", "pharmacy_charges", "total_amount", "service_date",
    },
    DocumentType.LAB_REPORT.value: {
        "patient_name", "date_of_birth", "age", "gender", "hospital_name", "doctor_name",
        "admission_date", "discharge_date", "diagnosis", "total_amount",
        "policy_number", "member_id", "patient_id", "service_date", "investigation_charges", "icd_code",
        "laboratory_charges", "radiology_charges", "other_charges",
        "isolation_charges", "transplant_charges", "chemotherapy_charges", "blood_charges",
    },
    DocumentType.UNKNOWN.value: {
        "policy_number", "member_id", "patient_id", "claim_number", "hospital_name", "service_date",
    },
}

_DOC_TYPE_PRIORITY: dict[str, int] = {
    DocumentType.DISCHARGE_SUMMARY.value: 0,
    DocumentType.HOSPITAL_BILL.value: 1,
    DocumentType.LAB_REPORT.value: 2,
    DocumentType.PHARMACY_INVOICE.value: 3,
    DocumentType.UNKNOWN.value: 4,
}


def _infer_coordinates_from_text(text: str) -> list[dict[str, Any]]:
    coords: list[dict[str, Any]] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return coords
    total = max(len(lines), 1)
    for idx, line in enumerate(lines):
        y1 = int((idx / total) * 1000)
        y2 = int(((idx + 1) / total) * 1000)
        coords.append({
            "text": line.strip(),
            "bbox": {"x1": 0, "y1": y1, "x2": 1000, "y2": y2},
            "source": "ocr-line",
        })
    return coords


def _field_allowed_for_doc(field_name: str, doc_type: str) -> bool:
    allowed = _DOC_TYPE_FIELD_ALLOWLIST.get(doc_type)
    if not allowed:
        return True
    return field_name in allowed


def _split_cells_with_spans(line: str) -> list[tuple[str, int, int]]:
    if not line.strip():
        return []

    if "|" in line:
        cells: list[tuple[str, int, int]] = []
        cursor = 0
        for part in line.split("|"):
            start = cursor
            end = cursor + len(part)
            cursor = end + 1
            text = part.strip()
            if not text:
                continue
            lpad = len(part) - len(part.lstrip())
            rpad = len(part) - len(part.rstrip())
            cells.append((text, start + lpad, max(start + lpad, end - rpad)))
        return cells

    cells = []
    for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line):
        text = m.group(0).strip()
        if text:
            cells.append((text, m.start(), m.end()))
    return cells


def _char_span_to_x(span_start: int, span_end: int, line_len: int, bbox: dict[str, Any]) -> tuple[int, int]:
    x1 = int(bbox.get("x1", 0))
    x2 = int(bbox.get("x2", 1000))
    width = max(1, x2 - x1)
    denom = max(1, line_len)
    sx = x1 + int(width * (span_start / denom))
    ex = x1 + int(width * (span_end / denom))
    return sx, max(sx + 1, ex)


def _build_geometric_tables_from_coords(coords: list[dict[str, Any]], page_num: int) -> list[dict[str, Any]]:
    """
    Build tables using column header x-ranges and coordinate-aligned assignment.
    A value belongs to a column only when its bbox center falls inside the header x-range.
    """
    if not coords:
        return []

    tables: list[dict[str, Any]] = []
    line_entries: list[dict[str, Any]] = []
    for item in coords:
        text = (item.get("text") or "").strip()
        bbox = item.get("bbox") or {}
        if not text:
            continue
        line_entries.append({"text": text, "bbox": bbox})

    i = 0
    while i < len(line_entries):
        line = line_entries[i]["text"]
        lower = line.lower()
        is_header = (
            "amount" in lower
            and any(k in lower for k in ("description", "particular", "qty", "quantity", "rate", "unit", "price", "test", "drug"))
        )
        if not is_header:
            i += 1
            continue

        header_cells = _split_cells_with_spans(line)
        if len(header_cells) < 2:
            i += 1
            continue

        header_bbox = line_entries[i]["bbox"]
        line_len = max(1, len(line))
        columns: list[dict[str, Any]] = []
        for htext, s, e in header_cells:
            cx1, cx2 = _char_span_to_x(s, e, line_len, header_bbox)
            columns.append({"name": htext, "x1": cx1, "x2": cx2})

        rows: list[list[str]] = [[c["name"] for c in columns]]
        j = i + 1
        while j < len(line_entries):
            row_line = line_entries[j]["text"]
            if not row_line.strip():
                break
            row_cells = _split_cells_with_spans(row_line)
            if len(row_cells) < 2:
                break

            row_bbox = line_entries[j]["bbox"]
            row_len = max(1, len(row_line))
            aligned = ["" for _ in columns]
            mapped_any = False
            for cell_text, s, e in row_cells:
                sx, ex = _char_span_to_x(s, e, row_len, row_bbox)
                center_x = (sx + ex) // 2
                assigned = False
                for idx, col in enumerate(columns):
                    if col["x1"] <= center_x <= col["x2"]:
                        aligned[idx] = (aligned[idx] + " " + cell_text).strip()
                        assigned = True
                        mapped_any = True
                        break
                if not assigned:
                    nearest_idx = min(
                        range(len(columns)),
                        key=lambda idx: abs(center_x - ((columns[idx]["x1"] + columns[idx]["x2"]) // 2)),
                    )
                    aligned[nearest_idx] = (aligned[nearest_idx] + " " + cell_text).strip()
                    mapped_any = True

            if not mapped_any:
                break

            if any(v.strip() for v in aligned):
                rows.append(aligned)
                j += 1
                continue
            break

        if len(rows) >= 2:
            tables.append({
                "source_page": page_num,
                "header": rows[0],
                "rows": rows,
                "row_count": len(rows),
                "spatial_alignment": {
                    "column_index": {
                        h.lower(): idx for idx, h in enumerate(rows[0])
                    },
                    "coordinate_space": "normalized_1000",
                },
            })
            i = j
            continue

        i += 1

    return tables


def _extract_tables_from_page(text: str, page_num: int, coords: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    # Try geometric first, then text-based, with fuzzy header matching
    base_tables = _build_geometric_tables_from_coords(coords or [], page_num)
    if not base_tables:
        base_tables = _detect_tables(text, page_num)
    # Fuzzy header rescue: try to find headers even if OCR is noisy
    for tbl in base_tables:
        header = tbl.get("header") or []
        if header and len(header) < 2:
            # Try to split header row by common delimiters if only one cell
            hrow = header[0]
            if isinstance(hrow, str):
                split = re.split(r"[|,\t]{1,}| {2,}", hrow)
                if len(split) > 1:
                    tbl["header"] = [h.strip() for h in split if h.strip()]

    if not settings.enable_spatial_table_mapping:
        return base_tables

    mapped: list[dict[str, Any]] = []
    for tbl in base_tables:
        header = tbl.get("header") or []
        rows = tbl.get("rows") or []
        if not header or len(rows) <= 1:
            mapped.append(tbl)
            continue

        hnorm = [str(h).strip().lower() for h in header]
        align_map: dict[str, int] = {}
        for i, h in enumerate(hnorm):
            # Fuzzy match for quantity/days/units
            if any(k in h for k in ("qty", "quantity", "days", "units")) or re.search(r"qty|quant|days?|units?", h):
                align_map["quantity_or_days"] = i
            if "amount" in h or re.search(r"amt|total|charge|price|rs|inr|paid", h):
                align_map["amount"] = i
            if "rate" in h or "price" in h:
                align_map["unit_price"] = i

        tbl["spatial_alignment"] = {
            "column_index": align_map,
            "coordinate_space": "normalized_1000",
        }
        mapped.append(tbl)
    return mapped


def _classify_page_document_type(page: PageObject) -> str:
    text = page.raw_text.lower()

    # Strong cues for full claim forms that include demographics + hospitalization + billing.
    if "medical insurance claim form" in text:
        return DocumentType.HOSPITAL_BILL.value
    if (
        "policy number" in text
        and ("date of admission" in text or "admission date" in text)
        and ("date of discharge" in text or "discharge date" in text)
    ):
        return DocumentType.HOSPITAL_BILL.value

    # Strong cue: page contains an expense table header or billing totals.
    # This overrides LAB_REPORT even if words like "laboratory" appear (they
    # are line-item labels inside the expense table, not lab-report headers).
    _BILLING_CUES = (
        "expense category", "hospital expense breakdown", "total amount",
        "claim amount requested", "billed total", "itemised total",
        "amount payable", "gross total", "amount exceeding policy",
        "inpatient hospital bill", "charges statement", "billing summary",
    )
    if any(cue in text for cue in _BILLING_CUES):
        return DocumentType.HOSPITAL_BILL.value

    scores: Dict[DocumentType, int] = {k: 0 for k in _DOC_KEYWORDS}
    for doc_type, keywords in _DOC_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[doc_type] += 1

    # Lightweight layout cue: dense numeric tables bias bill/lab/pharmacy.
    table_density = sum(1 for ln in text.splitlines() if re.search(r"\b\d[\d,]*\b", ln) and "|" in ln)
    if table_density >= 6:
        scores[DocumentType.HOSPITAL_BILL] += 1
        scores[DocumentType.LAB_REPORT] += 1

    best_type = max(scores, key=scores.get)
    if scores[best_type] <= 0:
        return DocumentType.UNKNOWN.value
    return best_type.value


def _build_page_objects(ocr_pages: List[Dict[str, Any]]) -> List[PageObject]:
    objs: List[PageObject] = []
    for page in sorted(ocr_pages, key=lambda p: (str(p.get("document_id", "")), int(p.get("page_number", 0)))):
        raw_text = (page.get("raw_text") or page.get("markdown") or page.get("text") or "").strip()
        page_num = int(page.get("page_number", 1) or 1)
        doc_id = page.get("document_id")
        coords = page.get("coordinates") or _infer_coordinates_from_text(raw_text)
        tables = _extract_tables_from_page(raw_text, page_num, coords)
        obj = PageObject(
            page_number=page_num,
            document_id=str(doc_id) if doc_id else None,
            raw_text=raw_text,
            detected_tables=tables,
            coordinates=coords,
        )
        if settings.enable_document_router:
            obj.document_type = _classify_page_document_type(obj)
        objs.append(obj)
    return objs


def _route_document_pages(page_objects: List[PageObject]) -> Dict[str, List[Dict[str, Any]]]:
    routed: Dict[str, List[Dict[str, Any]]] = {
        DocumentType.DISCHARGE_SUMMARY.value.lower(): [],
        DocumentType.LAB_REPORT.value.lower(): [],
        DocumentType.PHARMACY_INVOICE.value.lower(): [],
        DocumentType.HOSPITAL_BILL.value.lower(): [],
        DocumentType.UNKNOWN.value.lower(): [],
    }
    for page in page_objects:
        key = page.document_type.lower() if page.document_type else DocumentType.UNKNOWN.value.lower()
        routed.setdefault(key, []).append({
            "page_number": page.page_number,
            "document_id": page.document_id,
        })
    return routed


def _page_objects_to_ocr_pages(page_objects: List[PageObject]) -> List[Dict[str, Any]]:
    return [
        {
            "page_number": p.page_number,
            "text": p.raw_text,
            "markdown": p.raw_text,
            "document_id": p.document_id,
            "document_type": p.document_type,
            "tables": p.detected_tables,
            "coordinates": p.coordinates,
        }
        for p in page_objects
    ]


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_document(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[List[Image.Image]] = None,
) -> ParseOutput:
    """
    Parse structured fields from OCR text (and optionally page images).

    Parameters
    ----------
    ocr_pages : list of dicts with keys ``page_number``, ``text``
    images    : optional list of PIL Images (one per page) for LayoutLM

    Returns
    -------
    ParseOutput with extracted fields, tables, sections, model version, fallback flag.
    """
    page_objects = _build_page_objects(ocr_pages)
    document_boundaries = _route_document_pages(page_objects)
    routed_pages = _page_objects_to_ocr_pages(page_objects)

    if settings.structured_extraction_enabled:
        try:
            structured_output = _extract_with_structured_llm(routed_pages)
            if structured_output is not None:
                structured_output.page_objects = [
                    {
                        "page_number": p.page_number,
                        "document_id": p.document_id,
                        "document_type": p.document_type,
                        "raw_text": p.raw_text,
                        "detected_tables": p.detected_tables,
                        "coordinates": p.coordinates,
                    }
                    for p in page_objects
                ]
                structured_output.document_boundaries = document_boundaries
                _apply_vlm_code_priority(structured_output, routed_pages)
                return structured_output
        except Exception:
            logger.exception("Structured extraction failed — continuing with fallback chain")

    if images and _load_model():
        try:
            model_output = _extract_with_model(routed_pages, images)
            model_output.page_objects = [
                {
                    "page_number": p.page_number,
                    "document_id": p.document_id,
                    "document_type": p.document_type,
                    "raw_text": p.raw_text,
                    "detected_tables": p.detected_tables,
                    "coordinates": p.coordinates,
                }
                for p in page_objects
            ]
            model_output.document_boundaries = document_boundaries
            _apply_vlm_code_priority(model_output, routed_pages)
            return model_output
        except Exception:
            logger.exception("Model inference failed — falling back to heuristic")

    if settings.use_heuristic_fallback:
        heuristic_output = _extract_with_heuristic(page_objects)
        heuristic_output.document_boundaries = document_boundaries
        heuristic_output.page_objects = [
            {
                "page_number": p.page_number,
                "document_id": p.document_id,
                "document_type": p.document_type,
                "raw_text": p.raw_text,
                "detected_tables": p.detected_tables,
                "coordinates": p.coordinates,
            }
            for p in page_objects
        ]
        _apply_vlm_code_priority(heuristic_output, routed_pages)
        return heuristic_output

    return ParseOutput(used_fallback=True)


# ------------------------------------------------------------------
# Model-based extraction (LayoutLMv3)
# ------------------------------------------------------------------

def _extract_with_model(
    ocr_pages: List[Dict[str, Any]],
    images: List[Image.Image],
) -> ParseOutput:
    import torch

    all_fields: List[FieldResult] = []

    for page_info, img in zip(ocr_pages, images, strict=False):
        page_num = page_info.get("page_number", 1)
        text = page_info.get("text", "")
        words = text.split()
        if not words:
            continue

        word_boxes = page_info.get("word_boxes")
        if word_boxes and len(word_boxes) == len(words):
            boxes = word_boxes
        else:
            n = len(words)
            boxes = [
                [0, int(1000 * i / n), 1000, int(1000 * (i + 1) / n)]
                for i in range(n)
            ]

        encoding = _processor(
            img,
            words,
            boxes=boxes,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        with torch.no_grad():
            outputs = _model(**encoding)

        predictions = outputs.logits.argmax(-1).squeeze().tolist()
        if isinstance(predictions, int):
            predictions = [predictions]

        id2label = _model.config.id2label
        for word, pred in zip(words, predictions, strict=False):
            label = id2label.get(pred, "O")
            if label != "O":
                all_fields.append(
                    FieldResult(
                        field_name=label,
                        field_value=word,
                        source_page=page_num,
                        model_version=_model_version,
                    )
                )

    return ParseOutput(
        fields=all_fields,
        model_version=_model_version,
        used_fallback=False,
    )


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.lower() in {
        "unknown", "n/a", "na", "not available", "none", "null", "nil", "-",
    }:
        return None
    return cleaned


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_declared_total_from_ocr(ocr_pages: List[Dict[str, Any]]) -> Optional[float]:
    # Priority order matters: claim-declaration totals are more trustworthy than generic totals.
    prioritized_patterns = [
        re.compile(r"(?:claimed\s*amount|amount\s*claimed|total\s*amount\s*claimed)\s*[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I),
        re.compile(r"(?:net\s*(?:amount|payable)|amount\s*payable|final\s*bill\s*amount)\s*[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I),
        re.compile(r"(?:grand\s*total|total\s*(?:amount|bill|charges?|payable))\s*[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I),
    ]

    text = "\n".join((page.get("text") or "") for page in ocr_pages)
    for pattern in prioritized_patterns:
        matches = [m.group(1) for m in pattern.finditer(text)]
        # Prefer the last mention for summary-style documents.
        for raw in reversed(matches):
            value = _safe_float(raw)
            if value is not None and value > 0:
                return value
    return None


def _extract_code_page_map(ocr_pages: List[Dict[str, Any]]) -> tuple[Dict[str, int], Dict[str, int]]:
    icd_page: Dict[str, int] = {}
    cpt_page: Dict[str, int] = {}
    for page in ocr_pages:
        page_num = int(page.get("page_number", 1) or 1)
        stream = (page.get("markdown") or page.get("text") or "")
        if not stream:
            continue
        for code in _PAT_ICD_CODE.findall(stream):
            norm = code.strip().upper()
            if norm and norm not in icd_page:
                icd_page[norm] = page_num
        for m in _PAT_CPT_CODE.finditer(stream):
            line = _extract_line_for_match(stream, m)
            if _CPT_REJECT_CONTEXT.search(line):
                continue
            norm = m.group(1).strip()
            if norm and norm not in cpt_page:
                cpt_page[norm] = page_num
    return icd_page, cpt_page


def _apply_vlm_code_priority(output: ParseOutput, ocr_pages: List[Dict[str, Any]]) -> None:
    if not settings.prefer_vlm_codes:
        return

    icd_page, cpt_page = _extract_code_page_map(ocr_pages)
    if not icd_page and not cpt_page:
        return

    retained: List[FieldResult] = []
    for field in output.fields:
        if field.field_name in {"icd_code", "cpt_code"}:
            continue
        retained.append(field)

    for code, page_num in sorted(icd_page.items(), key=lambda kv: (kv[1], kv[0])):
        retained.append(
            FieldResult(
                field_name="icd_code",
                field_value=code,
                source_page=page_num,
                model_version=settings.vlm_code_model_version,
            )
        )

    for code, page_num in sorted(cpt_page.items(), key=lambda kv: (kv[1], kv[0])):
        retained.append(
            FieldResult(
                field_name="cpt_code",
                field_value=code,
                source_page=page_num,
                model_version=settings.vlm_code_model_version,
            )
        )

    output.fields = retained


def _build_structured_prompt(ocr_pages: List[Dict[str, Any]], max_chars: Optional[int] = None) -> str:
    ordered = sorted(ocr_pages, key=lambda p: p.get("page_number", 1))
    chunks: List[str] = []
    for page in ordered:
        pnum = page.get("page_number", "?")
        preferred_stream = page.get("markdown") if settings.structured_prefer_markdown_stream else None
        text = (preferred_stream or page.get("text") or "").strip()
        if text:
            chunks.append(f"[PAGE {pnum}]\n{text}")
    raw_text = "\n\n".join(chunks)
    effective_max_chars = max_chars or settings.structured_max_chars
    if len(raw_text) > effective_max_chars:
        raw_text = raw_text[: effective_max_chars]

    return (
        "You are extracting data from hospital claim documents.\n"
        "Return ONLY valid JSON for the provided schema.\n"
        "Hard rules:\n"
        "1) Do not guess. If a value is not explicitly present, return null.\n"
        "2) primary_diagnosis must be the reason for admission or principal diagnosis.\n"
        "3) Extract bill_line_items row-wise from billing tables/statements and preserve table semantics from markdown.\n"
        "4) Use numeric values for amounts, quantity, and unit_price.\n"
        "5) confidence must be one of HIGH, MEDIUM, LOW.\n"
        "6) No markdown, no commentary, no extra keys.\n\n"
        "Document OCR markdown stream:\n"
        f"{raw_text}"
    )


def _call_structured_llm(prompt: str) -> Optional[StructuredClaimExtraction]:
    global _llm_unavailable_logged
    schema = StructuredClaimExtraction.model_json_schema()

    # Only use HTTP endpoint, skip local LLM
    payload = {
        "model": settings.llm_model,
        "prompt": prompt,
        "stream": False,
        "format": schema,
        "options": {
            "temperature": 0,
        },
    }

    req = urlrequest.Request(
        settings.llm_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=settings.llm_timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        _llm_unavailable_logged = False
    except urlerror.URLError:
        if not _llm_unavailable_logged:
            logger.warning("Structured LLM endpoint unavailable at %s; using heuristic fallback", settings.llm_url)
            _llm_unavailable_logged = True
        else:
            logger.debug("Structured LLM endpoint still unavailable at %s", settings.llm_url)
        return None

    try:
        envelope = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Structured LLM returned non-JSON envelope")
        return None

    raw_response = envelope.get("response")
    if not isinstance(raw_response, str) or not raw_response.strip():
        logger.warning("Structured LLM response missing JSON payload")
        return None

    try:
        structured_data = json.loads(raw_response)
        return StructuredClaimExtraction.model_validate(structured_data)
    except (json.JSONDecodeError, ValidationError):
        logger.warning("Structured LLM payload did not match expected schema")
        return None


def _extract_with_structured_llm(ocr_pages: List[Dict[str, Any]]) -> Optional[ParseOutput]:
    if not ocr_pages:
        return None

    prompt = _build_structured_prompt(ocr_pages)
    extraction = _call_structured_llm(prompt)
    if extraction is None and settings.structured_retry_chars > 0:
        # Retry once with a shorter OCR context to avoid long-running local LLM timeouts.
        retry_prompt = _build_structured_prompt(ocr_pages, max_chars=settings.structured_retry_chars)
        extraction = _call_structured_llm(retry_prompt)

    # Final fallback for large/multi-document claims: run structured extraction per document
    # and merge partial outputs. This reduces timeout risk with long OCR contexts.
    if extraction is None and len(ocr_pages) > 1:
        grouped_pages: Dict[str, List[Dict[str, Any]]] = {}
        for p in ocr_pages:
            did = str(p.get("document_id") or "")
            key = did or f"page-{p.get('page_number', '?')}"
            grouped_pages.setdefault(key, []).append(p)

        merged: Optional[StructuredClaimExtraction] = None
        # Deterministic order for reproducibility.
        for _, pages in sorted(grouped_pages.items(), key=lambda kv: kv[0]):
            chunk_prompt = _build_structured_prompt(
                pages,
                max_chars=settings.structured_retry_chars or 8000,
            )
            chunk_extraction = _call_structured_llm(chunk_prompt)
            if chunk_extraction is None:
                continue
            merged = _merge_structured_extractions(merged, chunk_extraction)
        extraction = merged

    if extraction is None:
        return None

    line_items: List[BillingLineItem] = []
    dedupe_seen: set[tuple[str, float]] = set()
    for item in extraction.bill_line_items:
        amt = _safe_float(item.amount)
        qty = _safe_float(item.quantity)
        unit = _safe_float(item.unit_price)
        description = item.description.strip()
        if amt is not None:
            dedupe_key = (description.lower(), round(amt, 2))
            if dedupe_key in dedupe_seen:
                continue
            dedupe_seen.add(dedupe_key)
        line_items.append(
            BillingLineItem(
                description=description,
                category=_clean_optional_text(item.category),
                quantity=qty,
                unit_price=unit,
                amount=amt,
            )
        )

    computed_total = sum(item.amount for item in line_items if item.amount is not None)
    claimed_total = _safe_float(extraction.claimed_total)
    declared_total = _extract_declared_total_from_ocr(ocr_pages)

    # If LLM does not provide a trustworthy total, use explicit OCR-declared total.
    if claimed_total is None and declared_total is not None:
        claimed_total = declared_total
    elif claimed_total is not None and declared_total is not None:
        if abs(claimed_total - declared_total) > 0.01:
            # OCR-declared claimed amount is treated as authoritative when it conflicts.
            claimed_total = declared_total

    confidence = (extraction.confidence or "HIGH").upper()
    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        confidence = "MEDIUM"

    if claimed_total is not None and abs(claimed_total - computed_total) > 0.01:
        confidence = "LOW"

    fields: List[FieldResult] = []
    first_page = ocr_pages[0].get("page_number", 1)

    def add_field(name: str, value: Optional[str], model_version: str) -> None:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            return
        fields.append(
            FieldResult(
                field_name=name,
                field_value=cleaned,
                source_page=first_page,
                model_version=model_version,
            )
        )

    model_version = f"{settings.llm_model}-structured-v1"

    add_field("patient_name", extraction.patient_name, model_version)
    if extraction.age is not None:
        add_field("age", str(extraction.age), model_version)
    add_field("member_id", extraction.member_id, model_version)
    add_field("policy_number", extraction.policy_number, model_version)
    add_field("hospital_name", extraction.hospital_name, model_version)
    add_field("admission_date", extraction.admission_date, model_version)
    add_field("discharge_date", extraction.discharge_date, model_version)
    add_field("diagnosis", extraction.primary_diagnosis, model_version)
    add_field("secondary_diagnosis", extraction.secondary_diagnosis, model_version)
    add_field("doctor_name", extraction.treating_doctor, model_version)
    add_field("confidence", confidence, model_version)

    for proc in extraction.procedures:
        add_field("procedure", proc, model_version)

    if claimed_total is not None:
        add_field("claimed_total", f"{claimed_total:.2f}", model_version)
    add_field("calculated_total", f"{computed_total:.2f}", model_version)
    total_value = claimed_total if claimed_total is not None else computed_total
    add_field("total_amount", f"{total_value:.2f}", model_version)

    category_totals: Dict[str, float] = {}
    table_rows: List[List[str]] = []
    for item in line_items:
        amount = item.amount if item.amount is not None else 0.0
        inferred_category = _categorise_expense(item.category or item.description)
        category_totals[inferred_category] = category_totals.get(inferred_category, 0.0) + amount
        table_rows.append([
            item.description,
            item.category or "",
            "" if item.quantity is None else f"{item.quantity:.2f}",
            "" if item.unit_price is None else f"{item.unit_price:.2f}",
            f"{amount:.2f}",
        ])

    for category_name, amount in category_totals.items():
        add_field(category_name, f"{amount:.2f}", model_version)

    sections: List[Dict[str, Any]] = []
    notes = _clean_optional_text(extraction.notes)
    if notes:
        sections.append({
            "section_name": "structured_notes",
            "content": notes,
            "source_page": first_page,
        })

    tables: List[Dict[str, Any]] = []
    if table_rows:
        tables.append({
            "source_page": first_page,
            "header": ["description", "category", "quantity", "unit_price", "amount"],
            "rows": table_rows,
            "row_count": len(table_rows),
        })

    logger.info(
        "Structured extraction complete — fields=%d, line_items=%d, confidence=%s",
        len(fields),
        len(line_items),
        confidence,
    )

    return ParseOutput(
        fields=fields,
        tables=tables,
        sections=sections,
        model_version=model_version,
        used_fallback=False,
    )


# ------------------------------------------------------------------
# Advanced heuristic extraction
# ------------------------------------------------------------------

# ---- Patient demographics ----
_PAT_PRINCIPAL_DIAG_ROW = re.compile(
    r"(?im)^\s*principal(?:\s*\|)?\s*(.+?)\s*(?:\|\s*)?([A-TV-Z]\d{2}(?:\.\d{1,4})?)\s*$"
)

_PAT_PATIENT_NAME = re.compile(
    r"(?:(?:patient|pt)\s*(?:'s\s*)?name|name\s*of\s*(?:the\s*)?patient|(?<!hospital\s)(?<!test\s)(?<!drug\s)(?<!father\s)(?<!mother\s)(?<!spouse\s)(?<!doctor\s)\bname\b)(?:[ \t]*[:\-]+[ \t]*|[ \t]+)([^\n\r|]+?)(?=\s+(?:date\s*of\s*birth|dob|gender|age|sex|address|phone|email|member\s*id|policy\s*number|ip\s*/?\s*mrn\s*no|mrn\s*no|uhid|patient\s*id|prescriber|ordering\s*doctor|doctor|dr\.?|reg|date)(?:\b|_)|[\n|]|$)",
    re.I,
)
_PAT_DOB = re.compile(
    r"(?:date\s*of\s*birth|dob|d\.o\.b|birth\s*date)\s*[:\-]?\s*([0-3]?\d(?:[\-/\.](?:[A-Za-z]{3,9}|\d{1,2})[\-/\.]\d{2,4}|[-\s][A-Za-z]{3,9}[-\s]\d{2,4}))", re.I
)
_PAT_AGE = re.compile(
    r"(?i)(?:patient\s*age|age\s*/\s*(?:sex|gender)|age\s*(?:/\s*gender)?|\bage\b)\s*[:\-.]?\s*(\d{1,3})(?:\s*(?:years?|yrs?|y)\b)?(?:\s*[/,\-]\s*(?:male|female|m|f|other|transgender)\b)?"
)
_PAT_GENDER = re.compile(
    r"(?:gender|sex|age\s*/\s*gender)\s*[:\-]?\s*(?:\d{1,3}\s*[/\-]\s*)?(male|female|m|f|other|transgender)", re.I
)
_PAT_ADDRESS = re.compile(
    r"(?:address|patient\s*address|residential\s*address)\s*[:\-]?\s*(.+)", re.I
)
_PAT_PHONE = re.compile(
    r"(?:phone|mobile|contact\s*(?:no|number)|tel)\s*[:\-]?\s*([\d\+\-\(\)\s]{7,15})", re.I
)
_PAT_EMAIL = re.compile(
    r"(?:email|e-mail)\s*[:\-]?\s*([\w\.\-]+@[\w\.\-]+[\.\s]\w+)", re.I
)
_PAT_PATIENT_ID = re.compile(
    r"(?:patient\s*id|patient\s*no|uhid|mr\s*no|mrd\s*no|ipd\s*no)\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_SECONDARY_DIAG = re.compile(
    r"(?:secondary\s*diagnosis|additional\s*diagnosis|co-?morbid(?:ity|ities)?)\s*[:\-]?\s*(.+)", re.I
)

# ---- Insurance / policy ----
_PAT_POLICY = re.compile(
    r"(?:policy\s*(?:no|number|#|id)|insurance\s*(?:no|number|id)|health\s*id)\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_CLAIM_NO = re.compile(
    r"(?:claim\s*(?:no|number|#|id|ref)|reference\s*(?:no|number))\s*[:\-]?\s*([A-Z]{2,}[\-/]?[\w\-/]{3,})", re.I
)
_PAT_MEMBER_ID = re.compile(
    r"(?:member\s*(?:id|no|number|#)|uhid|mr\s*(?:no|number)|mrd\s*(?:no|number)|ipd\s*(?:no|number))\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_GROUP = re.compile(
    r"(?:group\s*(?:no|number|#|id)|corp(?:orate)?\s*(?:id|no))\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_INSURER = re.compile(
    r"(?:(?:insurer|insurance\s*(?:company|carrier|provider)|payer|tpa|third\s*party)(?:\s*name)?|insurer\s*/\s*tpa|tpa\s*/\s*insurer)\s*[:\-]\s*([^\n\r|]+?)(?=\s*(?:\||policy\s*(?:no|number)|member\s*id)|$)", re.I
)

# ---- Clinical / diagnosis ----
_PAT_DIAGNOSIS = re.compile(
    r"(?im)(?:(?:primary|principal|final|provisional|admitting|discharge)\s+)?(?<!secondary\s)diagnosis\s*[:\-/]\s*([^\n\r|]+?)(?=\s+(?:secondary\s+diagnosis|icd(?:-?10)?\s*code|procedure|treatment|admission|discharge|total\s*amount)\b|$)",
    re.I | re.M,
)
_PAT_ICD_CODE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,4})?)\b")
_PAT_PROCEDURE = re.compile(
    r"(?:procedure\s*performed|procedure(?:s)?|surgical?\s*procedure|operation\s*performed|cpt)\s*[:\-]?\s*(.+)", re.I
)
_PAT_CPT_CODE = re.compile(r"\b(\d{5})\b")
_PAT_MEDICATION = re.compile(
    r"^(?:medication(?:s)?|medicine(?:s)?|drug(?:s)?|prescription|rx)\s*[:\-]\s*(.+)", re.I | re.M
)
_PAT_ALLERGY = re.compile(
    r"(?:allerg(?:y|ies)|known\s*allerg(?:y|ies)|drug\s*allerg(?:y|ies))\s*[:\-]?\s*(.+)", re.I
)
_PAT_CHIEF_COMPLAINT = re.compile(
    r"(?:chief\s*complaint|presenting\s*complaint|reason\s*for\s*(?:admission|visit)|c/c)\s*[:\-]?\s*(.+)", re.I
)
_PAT_HISTORY = re.compile(
    r"(?:history\s*of\s*present\s*illness|hpi|brief\s*history|clinical\s*history)\s*[:\-]?\s*(.+)", re.I
)

# ---- Financial / billing ----
_PAT_TOTAL_AMOUNT = re.compile(
    r"(?:(?:total|gross\s*total)\s*(?:amount|charge|cost|billed|bill|payable|hospital\s*expenses|claimed\s*amount)|(?:total\s*)?gross\s*(?:total\s*)?amount|grand\s*total|net\s*(?:amount|payable)|claim\s*amount\s*requested)\s*[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?([\d,]+\.?\d*)",
    re.I,
)
_PAT_ROOM_CHARGE = re.compile(
    r"(?:room\s*(?:charges?|rent|rate)|bed\s*charges?|room\s*&?\s*board)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_CONSULTATION = re.compile(
    r"(?:consultation\s*(?:charges?|fees?)|doctor(?:'s)?\s*(?:fees?|charges?)|physician\s*(?:fees?|charges?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_PHARMACY = re.compile(
    r"(?:pharmacy|pharma\s*(?:charges?|cost)|medicines?\s*(?:&\s*(?:consumables?|surgical)|charges?|cost)|drug\s*(?:charges?|cost))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_INVESTIGATION = re.compile(
    r"(?:investigations?\s*(?:charges?|cost)?|diagnostics?\s*(?:&\s*investigations?|charges?|cost)?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_LABORATORY = re.compile(
    r"(?:lab(?:oratory)?\s*(?:charges?|cost|fees?)|pathology\s*(?:charges?|cost|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_RADIOLOGY = re.compile(
    r"(?:radiology\s*(?:charges?|cost|fees?)|imaging\s*(?:charges?|cost|fees?)|x[\-\s]?ray\s*(?:charges?|cost|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_SURGERY_CHARGE = re.compile(
    r"(?:surgery\s*(?:charges?|cost|fees?)|surgical?\s*(?:charges?|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_SURGEON_FEE = re.compile(
    r"(?:surgeon(?:'s)?\s*(?:&\s*professional\s*)?(?:fees?|charges?)|surgeon\s*fees?|professional\s*fees?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_ANAESTHESIA = re.compile(
    r"(?:an(?:ae|e)sthes(?:ia|ist)\s*(?:charges?|fees?)|an(?:ae|e)sthesia)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_OT_CHARGE = re.compile(
    r"(?:ot\s*charges?|operation\s*theat(?:re|er)\s*(?:charges?)?|theatre\s*charges?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_CONSUMABLES = re.compile(
    r"(?:(?:medical\s*(?:&\s*)?)?(?:surgical\s*)?(?:consumables?|disposables?)|implants?\s*&\s*consumables?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_NURSING = re.compile(
    r"(?:nursing\s*(?:&\s*(?:support|hospital)\s*(?:services?|charges?)|charges?|fees?)|nurse\s*charges?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_ICU_CHARGE = re.compile(
    r"(?:icu\s*(?:charges?|rent|cost)|intensive\s*care\s*(?:charges?|cost))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_AMBULANCE = re.compile(
    r"(?:ambulance\s*(?:charges?|cost|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_MISC_CHARGE = re.compile(
    r"(?:miscellaneous|misc\.?\s*charges?|other\s*(?:charges?|expenses?)|sundry)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)

# ---- Provider / facility ----
_PAT_HOSPITAL = re.compile(
    r"(?:hospital|facility|clinic|medical\s*(?:centre|center)|nursing\s*home)\s*name\s*[:\-]\s*([^\n\r|]+?)(?=\s+(?:registration|address|contact|doctor|admission|discharge)\b|$)",
    re.I,
)
_PAT_DOCTOR = re.compile(
    r"(?:(?:treating|attending|consulting|referring)\s*(?:doctor|physician)|dr\.?\s*name|doctor\s*(?:name)?|physician|consultant)\s*[:\-|]?\s*(?:dr\.?\s*)?([^\n\r|]+?)(?=\s+(?:registration|reg\.?\s*(?:no|number)|speciality|specialty|department|contact|phone|admission|discharge|sr\.?\s*no_?|days|qty|total|charges|description)(?:\b|_)|[\n|]|$)",
    re.I,
)
_PAT_REG_NO = re.compile(
    r"(?:registration\s*(?:no|number)|reg\.?\s*(?:no|number|#))\s*[:\-]?\s*([\w\-/]+)", re.I
)

# ---- Dates ----
_PAT_ADMISSION_DATE = re.compile(
    r"(?:date\s*of\s*admission|admission\s*date|admitted\s*on|doa)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)
_PAT_DISCHARGE_DATE = re.compile(
    r"(?:date\s*of\s*discharge|discharge\s*date|discharged\s*on|dod)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)
_PAT_SERVICE_DATE = re.compile(
    r"(?:date\s*of\s*service|service\s*date|dos|bill\s*date|invoice\s*date)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)

# ---- Vitals ----
_PAT_BLOOD_PRESSURE = re.compile(
    r"(?:blood\s*pressure|bp|b\.p)\s*[:\-]?\s*(\d{2,3}\s*/\s*\d{2,3})", re.I
)
_PAT_PULSE = re.compile(
    r"(?:pulse|heart\s*rate|hr)\s*[:\-]?\s*(\d{2,3})\s*(?:/min|bpm)?", re.I
)
_PAT_TEMPERATURE = re.compile(
    r"(?:temperature|temp)\s*[:\-]?\s*(\d{2,3}\.?\d*)\s*(?:°?[FCfc]|deg)?", re.I
)
_PAT_SPO2 = re.compile(
    r"(?:spo2|sp02|oxygen\s*saturation|o2\s*sat)\s*[:\-]?\s*(\d{2,3})%?", re.I
)

# Consolidated pattern list for iteration
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Demographics
    ("patient_name", _PAT_PATIENT_NAME),
    ("date_of_birth", _PAT_DOB),
    ("age", _PAT_AGE),
    ("gender", _PAT_GENDER),
    ("address", _PAT_ADDRESS),
    ("phone", _PAT_PHONE),
    ("email", _PAT_EMAIL),
    ("patient_id", _PAT_PATIENT_ID),
    ("secondary_diagnosis", _PAT_SECONDARY_DIAG),
    # Insurance
    ("policy_number", _PAT_POLICY),
    ("claim_number", _PAT_CLAIM_NO),
    ("member_id", _PAT_MEMBER_ID),
    ("group_number", _PAT_GROUP),
    ("insurer", _PAT_INSURER),
    # Clinical
    ("diagnosis", _PAT_DIAGNOSIS),
    ("icd_code", _PAT_ICD_CODE),
    ("procedure", _PAT_PROCEDURE),
    ("cpt_code", _PAT_CPT_CODE),
    ("medication", _PAT_MEDICATION),
    ("allergy", _PAT_ALLERGY),
    ("chief_complaint", _PAT_CHIEF_COMPLAINT),
    ("history_of_present_illness", _PAT_HISTORY),
    # Financial (order matters: more specific patterns first)
    ("total_amount", _PAT_TOTAL_AMOUNT),
    ("surgeon_fees", _PAT_SURGEON_FEE),
    ("anaesthesia_charges", _PAT_ANAESTHESIA),
    ("ot_charges", _PAT_OT_CHARGE),
    ("surgery_charges", _PAT_SURGERY_CHARGE),
    ("consumables", _PAT_CONSUMABLES),
    ("room_charges", _PAT_ROOM_CHARGE),
    ("consultation_charges", _PAT_CONSULTATION),
    ("pharmacy_charges", _PAT_PHARMACY),
    ("laboratory_charges", _PAT_LABORATORY),
    ("radiology_charges", _PAT_RADIOLOGY),
    ("investigation_charges", _PAT_INVESTIGATION),
    ("nursing_charges", _PAT_NURSING),
    ("icu_charges", _PAT_ICU_CHARGE),
    ("ambulance_charges", _PAT_AMBULANCE),
    ("misc_charges", _PAT_MISC_CHARGE),
    # Provider
    ("hospital_name", _PAT_HOSPITAL),
    ("doctor_name", _PAT_DOCTOR),
    ("registration_number", _PAT_REG_NO),
    # Dates
    ("admission_date", _PAT_ADMISSION_DATE),
    ("discharge_date", _PAT_DISCHARGE_DATE),
    ("service_date", _PAT_SERVICE_DATE),
    # Vitals
    ("blood_pressure", _PAT_BLOOD_PRESSURE),
    ("pulse", _PAT_PULSE),
    ("temperature", _PAT_TEMPERATURE),
    ("spo2", _PAT_SPO2),
]


# ---- Section detection for discharge summaries ----
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("chief_complaint", re.compile(r"^(?:chief\s*complaint|presenting\s*complaint|c/c|reason\s*for\s*(?:admission|visit))\s*[:\-]?", re.I | re.M)),
    ("history_of_present_illness", re.compile(r"^(?:history\s*of\s*present\s*illness|hpi|brief\s*history|clinical\s*history)\s*[:\-]?", re.I | re.M)),
    ("past_medical_history", re.compile(r"^(?:past\s*(?:medical\s*)?history|pmh|past\s*illness)\s*[:\-]?", re.I | re.M)),
    ("examination_findings", re.compile(r"^(?:(?:on\s*)?examination|physical\s*examination|clinical\s*findings|general\s*examination|systemic\s*examination)\s*[:\-]?", re.I | re.M)),
    ("investigations", re.compile(r"^(?:investigations?|lab(?:oratory)?\s*(?:results?|findings?)|diagnostic\s*(?:results?|findings?))\s*[:\-]?", re.I | re.M)),
    ("diagnosis_section", re.compile(r"^(?:(?:final|principal|primary|provisional)\s*)?diagnosis\s*[:\-]?", re.I | re.M)),
    ("treatment_given", re.compile(r"^(?:treatment\s*(?:given|provided|administered)|course\s*(?:in\s*(?:hospital|ward))|management)\s*[:\-]?", re.I | re.M)),
    ("procedure_section", re.compile(r"^(?:procedure(?:s)?\s*(?:performed|done)?|surgical?\s*(?:procedure|note)|operation\s*(?:performed|note))\s*[:\-]?", re.I | re.M)),
    ("medications_at_discharge", re.compile(r"^(?:(?:medication|medicine|drug)(?:s)?\s*(?:at|on)\s*discharge|discharge\s*(?:medication|medicine)(?:s)?|rx)\s*[:\-]?", re.I | re.M)),
    ("follow_up", re.compile(r"^(?:follow\s*[-\s]?up|advice\s*(?:on|at)\s*discharge|discharge\s*advice|instructions)\s*[:\-]?", re.I | re.M)),
    ("condition_at_discharge", re.compile(r"^(?:condition\s*(?:at|on)\s*discharge|discharge\s*(?:condition|status))\s*[:\-]?", re.I | re.M)),
]


def _normalize_amount(raw: str) -> str:
    """Normalize currency amounts: remove commas, ensure decimal format."""
    cleaned = raw.replace(",", "").strip()
    # Ensure it looks like a number
    try:
        val = float(cleaned)
        return f"{val:.2f}"
    except ValueError:
        return cleaned


_CPT_REJECT_CONTEXT = re.compile(
    r"(?:phone|mobile|contact|claim\s*ref|claim\s*no|authorization|auth\.?\s*no|reg\.?\s*no|invoice|bill\s*no|policy|member|aadhaar|receipt|ip\s*/\s*mrn|mrn|charges?|total|amount|rs|inr|deposits?|payable|balance|paid|price|qty|quantity|rate)",
    re.I,
)


_MONEY_FIELDS = {
    "total_claimed", "sum_insured", "hospital_daily_cash", "surgical_cash",
    "critical_illness_benefit", "convalescence_benefit", "pre_hospitalization_expenses",
    "post_hospitalization_expenses", "ambulance_charges", "room_charges",
    "consultation_charges", "pharmacy_charges", "laboratory_charges",
    "radiology_charges", "investigation_charges", "surgery_charges",
    "surgeon_fees", "anaesthesia_charges", "ot_charges", "consumables",
    "nursing_charges", "icu_charges", "misc_charges", "other_charges",
    "isolation_charges", "transplant_charges", "chemotherapy_charges", "blood_charges",
    "physiotherapy_charges",
}


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", "").strip())
    except Exception:
        return None


def _extract_line_for_match(text: str, match: re.Match[str]) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _infer_gender_from_patient_name(name: str | None) -> Optional[str]:
    if not name:
        return None
    normalized = (name or "").strip().lower()
    if re.match(r"^(?:mr\.?|master)\b", normalized):
        return "male"
    if re.match(r"^(?:mrs\.?|ms\.?|miss|smt\.?)\b", normalized):
        return "female"
    return None


def _extract_hospital_name_fallback(text: str) -> Optional[str]:
    for raw_line in text.splitlines()[:60]:
        line = re.sub(r"\s+", " ", (raw_line or "").strip())
        if not line:
            continue
        low = line.lower()
        # Look for any provider/institution keywords (broader than just 'hospital')
        if not any(tok in low for tok in (
            "hospital", "maternity", "clinic", "home", "centre", "center",
            "institute", "netaralay", "nursing", "care", "dispensary", "health",
        )):
            continue
        if any(tok in low for tok in (
            "hospital course", "hospitalization", "inpatient hospital bill",
            "hospital expense", "hospital charges", "hospital bill",
        )):
            continue

        # Keep only the hospital title segment before obvious address/noise suffixes.
        candidate = line.split("+")[0].strip()
        if "," in candidate:
            left, right = candidate.split(",", 1)
            if re.search(r"\d", right):
                candidate = left.strip()
        candidate = candidate.strip(" .,:;|-_")

        if not re.search(r"[A-Za-z]", candidate):
            continue
        # Accept reasonably short provider names (e.g., 'Aniket Netaralay')
        if len(candidate) < 4 or len(candidate) > 120:
            continue
        # Ensure candidate contains at least one provider-like token
        if not re.search(r"(?:hospital(?:s)?|maternity|clinic|nursing|care|institute|center|centre|netaralay|dispensary|health)", candidate, re.I):
            continue
        return candidate
    return None


def _normalize_gender_value(value: str | None) -> Optional[str]:
    if not value:
        return None
    token = value.strip().lower()
    if token in {"m", "male"}:
        return "male"
    if token in {"f", "female"}:
        return "female"
    if token in {"other", "transgender"}:
        return token
    return None


def _doc_priority(doc_type: str | None) -> int:
    if not doc_type:
        return 99
    return _DOC_TYPE_PRIORITY.get(doc_type, 99)


def _backfill_demographic_fields(
    page_objects: List[PageObject],
    fields: List[FieldResult],
    seen_fields: Dict[str, set],
) -> None:
    """
    Fill key demographics from any accepted document type using priority order.
    This runs after normal extraction and only fills still-missing fields.
    """
    targets = ("patient_name", "date_of_birth", "age", "gender", "hospital_name")
    existing = {f.field_name for f in fields if f.field_value}
    missing = [t for t in targets if t not in existing]
    if not missing:
        return

    pattern_map: Dict[str, re.Pattern[str]] = {
        "patient_name": _PAT_PATIENT_NAME,
        "date_of_birth": _PAT_DOB,
        "age": _PAT_AGE,
        "gender": _PAT_GENDER,
        "hospital_name": _PAT_HOSPITAL,
    }

    sorted_pages = sorted(page_objects, key=lambda p: (_doc_priority(p.document_type), p.page_number))

    for page in sorted_pages:
        text = page.raw_text or ""
        if not text:
            continue

        for field_name in list(missing):
            candidate_value: Optional[str] = None
            line_context = ""

            pattern = pattern_map[field_name]
            match = pattern.search(text)
            if match:
                candidate_value = (match.group(1) if match.lastindex else match.group(0)).strip()
                line_context = _extract_line_for_match(text, match)

            if field_name == "hospital_name" and not candidate_value:
                candidate_value = _extract_hospital_name_fallback(text)
                line_context = candidate_value or ""

            if field_name == "gender":
                if candidate_value:
                    candidate_value = _normalize_gender_value(candidate_value)
                if not candidate_value:
                    inferred = None
                    for f in reversed(fields):
                        if f.field_name == "patient_name" and f.field_value:
                            inferred = _infer_gender_from_patient_name(f.field_value)
                            if inferred:
                                break
                    candidate_value = inferred
                    line_context = line_context or (candidate_value or "")

            if not candidate_value:
                continue

            if not _is_valid_field_value(field_name, candidate_value, line_context, page.document_type):
                continue

            key = f"{field_name}:{candidate_value.lower()}"
            bucket = seen_fields.setdefault(field_name, set())
            if key in bucket:
                continue
            bucket.add(key)
            fields.append(FieldResult(
                field_name=field_name,
                field_value=candidate_value,
                source_page=page.page_number,
                model_version="heuristic-v2-backfill",
            ))
            missing.remove(field_name)

        if not missing:
            return


def _validate_by_doc_schema(field_name: str, value: str, doc_type: str) -> bool:
    if not settings.enable_strict_field_validation:
        return True
    if doc_type == DocumentType.DISCHARGE_SUMMARY.value:
        model = DischargeSummarySchema
    elif doc_type == DocumentType.HOSPITAL_BILL.value:
        model = HospitalBillSchema
    elif doc_type == DocumentType.PHARMACY_INVOICE.value:
        model = PharmacyInvoiceSchema
    elif doc_type == DocumentType.LAB_REPORT.value:
        model = LabReportSchema
    else:
        return True

    if field_name not in model.model_fields:
        return True
    try:
        model.model_validate({field_name: value})
        return True
    except ValidationError:
        return False


def _is_valid_field_value(field_name: str, value: str, line_context: str, doc_type: str) -> bool:
    if not value.strip():
        return False

    if field_name == "cpt_code":
        if doc_type != DocumentType.DISCHARGE_SUMMARY.value:
            return False
        if not re.fullmatch(r"\d{5}", value.strip()):
            return False
        if _CPT_REJECT_CONTEXT.search(line_context):
            return False
        has_cpt_context = re.search(r"(?:cpt|procedure|operation|surgery|angiography|echocardiography)", line_context, re.I)
        if not has_cpt_context:
            # Allow procedure-table rows in discharge summaries where the CPT marker is in header lines.
            if not (
                re.search(r"\b\d{1,2}[-/]\w{3,9}[-/]\d{2,4}\b", line_context, re.I)
                and re.search(r"(?:dr\.?|pci|cag|stent|echo|monitoring)", line_context, re.I)
            ):
                return False

    if field_name == "insurer":
        if doc_type not in {DocumentType.DISCHARGE_SUMMARY.value, DocumentType.HOSPITAL_BILL.value}:
            return False
        cleaned = value.strip().lower()
        if len(cleaned) < 6:
            return False
        if cleaned.startswith("&"):
            return False
        if any(tok in cleaned for tok in ("remark", "communication note", "details", "risk level", "required document")):
            return False

    if field_name == "procedure":
        if doc_type != DocumentType.DISCHARGE_SUMMARY.value:
            return False
        cleaned = value.strip()
        if len(cleaned) < 8:
            return False
        if cleaned.startswith("/"):
            return False
        if re.fullmatch(r"[A-Z\s\|\-]+", cleaned):
            return False
        if cleaned.lower() in {"performed", "date cpt code surgeon / operator"}:
            return False
        lowered = cleaned.lower()
        if any(tok in lowered for tok in ("requested", "approved", "checklist", "cath lab report received")):
            return False
        if "cpt code" in lowered and ("surgeon" in lowered or "date" in lowered):
            return False

    if field_name in _MONEY_FIELDS:
        numeric = _to_float(value)
        if numeric is None:
            return False
        lowered_ctx = line_context.lower()
        if field_name == "total_amount" and re.search(r"(?:exceeding\s*policy|sum\s*insured)", lowered_ctx):
            return False
        # Regex extraction on dense table rows often captures qty/units (e.g., 1, 2, 3) instead of amount.
        if not re.search(r"(?:rs|inr|amount|total|payable|charges?|cost|fees?|itemized|breakdown|statement)", lowered_ctx):
            return False
        nums = [
            _to_float(tok)
            for tok in re.findall(r"\d[\d,]*\.?\d*", line_context)
        ]
        nums = [n for n in nums if n is not None]
        if nums and numeric < 100 and max(nums) >= 1000:
            return False

    if field_name == "doctor_name":
        cleaned_doc = value.strip().lower()
        if re.search(r"signature|_{3,}|initials?\s*:", cleaned_doc):
            return False
        if len(cleaned_doc) < 3:
            return False

    if field_name == "claim_number":
        # Must have at least 4 chars and contain a digit or dash to be a real claim ID
        if len(value.strip()) < 4:
            return False
        if not re.search(r"[\d\-/]", value):
            return False

    if field_name == "icd_code":
        if not re.fullmatch(r"[A-TV-Z]\d{2}(?:\.\d{1,4})?", value.strip(), flags=re.I):
            return False

    if field_name == "date_of_birth":
        if len(value.strip()) < 8:
            return False

    return _validate_by_doc_schema(field_name, value, doc_type)


_NER_MODEL = None


def _extract_medical_entities(text: str) -> Dict[str, List[str]]:
    if not settings.enable_medical_ner:
        return {}
    global _NER_MODEL
    try:
        if _NER_MODEL is None:
            import spacy
            _NER_MODEL = spacy.load(settings.scispacy_model)
        doc = _NER_MODEL(text)
        diagnosis_terms: List[str] = []
        procedure_terms: List[str] = []
        for ent in doc.ents:
            label = (ent.label_ or "").upper()
            val = ent.text.strip()
            if not val:
                continue
            if "DISEASE" in label or "DISORDER" in label:
                diagnosis_terms.append(val)
            if "PROCEDURE" in label:
                procedure_terms.append(val)
        return {
            "diagnosis": diagnosis_terms[:10],
            "procedure": procedure_terms[:10],
        }
    except Exception:
        logger.debug("scispaCy enrichment unavailable", exc_info=True)
        return {}


def _extract_procedure_section_text(text: str) -> str:
    start = re.search(r"(?:^|\n)\s*procedures?\s*performed\s*", text, re.I)
    if not start:
        return ""
    section = text[start.end():]
    end = re.search(
        r"(?:^|\n)\s*(?:final\s*diagnosis|hospital\s*course|discharge\s*condition|discharge\s*medications?|investigations?\s*summary)\b",
        section,
        re.I,
    )
    if end:
        section = section[: end.start()]
    return section.strip()


def _is_medical_procedure_text(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False

    keyword_hit = re.search(
        r"(?:angiograph|angioplasty|stent|echo(?:cardiography)?|monitoring|procedure|surgery|catheter|cath\s*lab|doppler|implant)",
        cleaned,
        re.I,
    )
    if keyword_hit:
        return True

    if not settings.enable_medical_ner:
        return False
    global _NER_MODEL
    try:
        if _NER_MODEL is None:
            import spacy
            _NER_MODEL = spacy.load(settings.scispacy_model)
        doc = _NER_MODEL(cleaned)
        for ent in doc.ents:
            if "PROCEDURE" in (ent.label_ or "").upper():
                return True
    except Exception:
        logger.debug("scispaCy procedure validation unavailable", exc_info=True)
    return False


def _extract_with_heuristic(page_objects: List[PageObject]) -> ParseOutput:
    """Advanced regex-based field extraction from OCR text."""
    fields: List[FieldResult] = []
    tables: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    seen_fields: Dict[str, set] = {}  # deduplicate identical extractions

    amount_fields = {
        "total_amount", "room_charges", "consultation_charges",
        "pharmacy_charges", "investigation_charges", "surgery_charges",
        "surgeon_fees", "anaesthesia_charges", "ot_charges",
        "consumables", "nursing_charges", "icu_charges",
        "ambulance_charges", "misc_charges", "other_charges",
        "laboratory_charges", "radiology_charges", "physiotherapy_charges",
    }

    for page in page_objects:
        page_num = page.page_number
        text = page.raw_text
        if not text:
            continue

        procedure_section_text = ""
        if page.document_type == DocumentType.DISCHARGE_SUMMARY.value:
            procedure_section_text = _extract_procedure_section_text(text)

        # --- Expense table extraction ---
        known_cpt_codes = {
            f.field_value for f in fields if f.field_name == "cpt_code"
        }
        for cpt_m in re.finditer(r"(?:CPT|cpt)\s*[:\-]?\s*(\d{5})\b", text):
            known_cpt_codes.add(cpt_m.group(1))

        is_bill = page.document_type in {DocumentType.HOSPITAL_BILL.value, DocumentType.PHARMACY_INVOICE.value}
        header_match = _EXPENSE_SECTION_HEADER.search(text)
        
        if is_bill or header_match:
            expense_fields, line_items = _extract_expense_table(
                text, page_num, page.detected_tables, known_cpt_codes
            )
        else:
            expense_fields, line_items = [], []
        has_expense_table = len(expense_fields) > 0
        for ef in expense_fields:
            key = f"{ef.field_name}:{ef.field_value}:{page_num}"
            if ef.field_name not in seen_fields:
                seen_fields[ef.field_name] = set()
            if key not in seen_fields[ef.field_name]:
                seen_fields[ef.field_name].add(key)
                fields.append(ef)

        if has_expense_table and line_items:
            table_rows = []
            for item in line_items:
                table_rows.append([
                    item.description,
                    item.category or "",
                    str(item.quantity) if item.quantity else "1.00",
                    f"{item.unit_price:.2f}" if item.unit_price else (f"{item.amount:.2f}" if item.amount else ""),
                    f"{item.amount:.2f}" if item.amount else ""
                ])
            tables.append({
                "source_page": page_num,
                "header": ["description", "category", "quantity", "unit_price", "amount"],
                "rows": table_rows,
                "row_count": len(table_rows),
            })

        # --- Field extraction (Heuristic Regexes) ---
        for field_name, pattern in _PATTERNS:
            if not _field_allowed_for_doc(field_name, page.document_type):
                continue

            # If we found a valid expense table on this page, do NOT run noisy regexes for itemised amounts
            if has_expense_table and field_name in amount_fields and field_name not in {"total_amount", "claimed_total"}:
                continue

            search_text = text
            if field_name in {"cpt_code", "procedure"}:
                if page.document_type != DocumentType.DISCHARGE_SUMMARY.value:
                    continue
                if not procedure_section_text:
                    continue
                search_text = procedure_section_text

            for match in pattern.finditer(search_text):
                value = match.group(1).strip() if match.lastindex else match.group(0).strip()
                if not value:
                    continue

                line_context = _extract_line_for_match(search_text, match)

                # --- Enhanced field validation and post-processing ---
                # Doctor name: must look like a person, not a table row
                if field_name in {"treating_doctor", "doctor_name"}:
                    if not re.search(r"[A-Za-z]{3,}", value) or re.search(r"total|charges?|amount|qty|days|description|category|grand|deposit|payable|room|summary|table|sr\b|sl\b|visit|medicine|head\s*of", value, re.I):
                        continue
                    # Avoid values that are mostly numbers or table-like
                    if sum(c.isdigit() for c in value) > sum(c.isalpha() for c in value):
                        continue

                # Age: must be a reasonable number
                if field_name == "age":
                    try:
                        age_val = int(re.sub(r"[^0-9]", "", value))
                        if not (0 < age_val < 120):
                            continue
                        value = str(age_val)
                    except:
                        continue

                # Hospital name: must contain 'hospital' and not be a table header
                if field_name == "hospital_name":
                    if not re.search(r"hospital|clinic|care|nursing|institute|center|maternity|netaralay", value, re.I):
                        continue
                    if re.search(r"charges?|amount|summary|table|room|total|bill|expense|category|date|sr\b|sl\b", value, re.I):
                        continue

                # Address: avoid over-extraction (should not contain diagnosis, summary, etc.)
                if field_name == "address":
                    if re.search(r"diagnosis|summary|charges?|amount|table|room|total|bill|expense|category|date|sr\b|sl\b", value, re.I):
                        continue

                # CPT code: only if context matches
                if field_name == "cpt_code":
                    if not re.search(r"cpt|procedure", line_context, re.I):
                        continue

                if not _is_valid_field_value(field_name, value, line_context, page.document_type):
                    continue

                # Normalize amounts
                if field_name in amount_fields:
                    value = _normalize_amount(value)

                # Deduplicate: skip if same field+value already seen
                key = f"{field_name}:{value.lower()}"
                if field_name not in seen_fields:
                    seen_fields[field_name] = set()
                if key in seen_fields[field_name]:
                    continue
                seen_fields[field_name].add(key)

                fields.append(
                    FieldResult(
                        field_name=field_name,
                        field_value=value,
                        source_page=page_num,
                        model_version="heuristic-v2",
                    )
                )

        # Discharge summaries often provide principal diagnosis in a table row
        if page.document_type == DocumentType.DISCHARGE_SUMMARY.value:
            m_principal = _PAT_PRINCIPAL_DIAG_ROW.search(text)
            if m_principal:
                principal_diag = m_principal.group(1).strip()
                principal_code = m_principal.group(2).strip()

                if principal_diag:
                    key = f"diagnosis:{principal_diag.lower()}"
                    if key not in seen_fields.setdefault("diagnosis", set()):
                        seen_fields["diagnosis"].add(key)
                        fields.append(FieldResult(
                            field_name="diagnosis",
                            field_value=principal_diag,
                            source_page=page_num,
                            model_version="heuristic-v2",
                        ))

                if principal_code:
                    key = f"icd_code:{principal_code.lower()}"
                    if key not in seen_fields.setdefault("icd_code", set()):
                        seen_fields["icd_code"].add(key)
                        fields.append(FieldResult(
                            field_name="icd_code",
                            field_value=principal_code,
                            source_page=page_num,
                            model_version="heuristic-v2",
                        ))

        # Fallbacks for common OCR/header layouts where labels are partially corrupted.
        if _field_allowed_for_doc("hospital_name", page.document_type) and not seen_fields.get("hospital_name"):
            inferred_hospital = _extract_hospital_name_fallback(text)
            if inferred_hospital:
                key = f"hospital_name:{inferred_hospital.lower()}"
                seen_fields.setdefault("hospital_name", set()).add(key)
                fields.append(FieldResult(
                    field_name="hospital_name",
                    field_value=inferred_hospital,
                    source_page=page_num,
                    model_version="heuristic-v2",
                ))

        if _field_allowed_for_doc("gender", page.document_type) and not seen_fields.get("gender"):
            latest_patient_name = None
            for f in reversed(fields):
                if f.field_name == "patient_name" and f.field_value:
                    latest_patient_name = f.field_value
                    break
            inferred_gender = _infer_gender_from_patient_name(latest_patient_name)
            if inferred_gender:
                key = f"gender:{inferred_gender.lower()}"
                seen_fields.setdefault("gender", set()).add(key)
                fields.append(FieldResult(
                    field_name="gender",
                    field_value=inferred_gender,
                    source_page=page_num,
                    model_version="heuristic-v2",
                ))

        # --- Table detection (improved) ---
        page_tables = page.detected_tables or _detect_tables(text, page_num)
        for table in page_tables:
            table.setdefault("document_type", page.document_type)
            table.setdefault("document_id", page.document_id)
        tables.extend(page_tables)

        # --- Section detection ---
        page_sections = _detect_sections(text, page_num)
        sections.extend(page_sections)

        # --- Optional medical NER enrichment ---
        ner = _extract_medical_entities(text)
        for diag in ner.get("diagnosis", []):
            key = f"diagnosis:{diag.lower()}"
            if key in seen_fields.setdefault("diagnosis", set()):
                continue
            seen_fields["diagnosis"].add(key)
            fields.append(FieldResult(
                field_name="diagnosis",
                field_value=diag,
                source_page=page_num,
                model_version="scispacy-ner",
            ))
        for proc in ner.get("procedure", []):
            key = f"procedure:{proc.lower()}"
            if key in seen_fields.setdefault("procedure", set()):
                continue
            seen_fields["procedure"].add(key)
            fields.append(FieldResult(
                field_name="procedure",
                field_value=proc,
                source_page=page_num,
                model_version="scispacy-ner",
            ))

    _backfill_demographic_fields(page_objects, fields, seen_fields)

    # Calculate implicit total amount if missing
    if not any(f.field_name == "total_amount" for f in fields):
        total = sum(float(f.field_value) for f in fields if f.field_name in amount_fields and f.field_name not in {"total_amount", "claimed_total"} and f.field_value)
        if total > 0:
            fields.append(FieldResult(
                field_name="total_amount",
                field_value=f"{total:.2f}",
                source_page=1,
                model_version="heuristic-v2"
            ))

    return ParseOutput(
        fields=fields,
        tables=tables,
        sections=sections,
        model_version="heuristic-v2",
        used_fallback=True,
    )


def _detect_tables(text: str, page_num: int) -> List[Dict[str, Any]]:
    """Detect and parse table-like structures with header detection."""
    lines = text.splitlines()
    table_rows: List[List[str]] = []
    header: Optional[List[str]] = None
    tables: List[Dict[str, Any]] = []

    for line in lines:
        # Split on pipe separators (from pdfplumber tables) or multi-space/tab
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
        else:
            cells = re.split(r"\t|  {2,}", line.strip())
            cells = [c.strip() for c in cells if c.strip()]

        if len(cells) >= 3:
            # Check if this looks like a header row (all non-numeric, short)
            if not table_rows and all(
                not re.match(r"^[\d,.\-$₹]+$", c) for c in cells
            ):
                header = cells
            table_rows.append(cells)
        else:
            # Break in table — flush if we have rows
            if len(table_rows) >= 2:
                tables.append({
                    "source_page": page_num,
                    "header": header,
                    "rows": table_rows,
                    "row_count": len(table_rows),
                })
            table_rows = []
            header = None

    # Flush remaining
    if len(table_rows) >= 2:
        tables.append({
            "source_page": page_num,
            "header": header,
            "rows": table_rows,
            "row_count": len(table_rows),
        })

    return tables


def _detect_sections(text: str, page_num: int) -> List[Dict[str, Any]]:
    """Detect medical document sections (discharge summary, reports)."""
    sections: List[Dict[str, Any]] = []
    matches: List[tuple[int, str, str]] = []

    for section_name, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), section_name, m.group()))

    if not matches:
        return sections

    # Sort by position in text
    matches.sort(key=lambda x: x[0])

    # Extract content between sections
    for i, (pos, name, header) in enumerate(matches):
        start = pos + len(header)
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        # Trim content to reasonable length (first 2000 chars)
        if len(content) > 2000:
            content = content[:2000] + "..."

        if content:
            sections.append({
                "section_name": name,
                "content": content,
                "source_page": page_num,
            })

    return sections


# ------------------------------------------------------------------
# Expense table extraction — smart billing line-item parser
# ------------------------------------------------------------------

_EXPENSE_SECTION_HEADER = re.compile(
    r"\b(?:(?:hospitali[sz]ation|hospital|medical|surgery|claimed)\s*(?:&\s*(?:surgery|treatment))?\s*)?(?:expense|billing|charges?|cost)\b\s*(?:summary|details?|breakdown|statement)?",
    re.I,
)

# Matches a line like: "Some Description   35,000" or "Room Rent (5 Days)  10,000"
# Requires 2+ spaces or tab between label and amount to avoid false positives
_EXPENSE_LINE = re.compile(
    r"^(.+?)(?:\s{2,}|\t+)\s*(?:(?:rs|inr|\$|₹)\.?\s*)?(\d[\d,]*\.?\d*)\s*$", re.M | re.I
)

# Normalised expense categories for deduplication
# ── EXACT LABEL LOOKUP (highest priority — bypasses keyword matching entirely) ──
_EXPENSE_LABEL_EXACT: Dict[str, str] = {
    # Direct label matches (case-insensitive lookup done in function)
    "room charges": "room_charges",
    "room charge": "room_charges",
    "room & boarding": "room_charges",
    "room / boarding charges": "room_charges",
    "room rent": "room_charges",
    "boarding charges": "room_charges",
    "ward charges": "room_charges",
    "general ward": "room_charges",
    "hdu charges": "icu_charges",
    "hdu": "icu_charges",
    "icu charges": "icu_charges",
    "icu charge": "icu_charges",
    "nicu charges": "icu_charges",
    "intensive care": "icu_charges",
    "haematology icu": "icu_charges",
    "hematology icu": "icu_charges",
    "consultation charges": "consultation_charges",
    "consultation charge": "consultation_charges",
    "consultation fee": "consultation_charges",
    "consultation fees": "consultation_charges",
    "consultation": "consultation_charges",
    "doctor charges": "consultation_charges",
    "doctor fee": "consultation_charges",
    "doctor fees": "consultation_charges",
    "physician charges": "consultation_charges",
    "surgery charges": "surgery_charges",
    "surgery charge": "surgery_charges",
    "surgical charges": "surgery_charges",
    "procedure charges": "surgery_charges",
    "procedure charge": "surgery_charges",
    "ot charges": "ot_charges",
    "ot charge": "ot_charges",
    "ot / angio charges": "ot_charges",
    "angio charges": "ot_charges",
    "cath lab charges": "ot_charges",
    "operation theatre charges": "ot_charges",
    "operation theatre": "ot_charges",
    "theatre charges": "ot_charges",
    "anaesthesia charges": "anaesthesia_charges",
    "anaesthesia charge": "anaesthesia_charges",
    "anaesthesia": "anaesthesia_charges",
    "anesthesia charges": "anaesthesia_charges",
    "anesthesia": "anaesthesia_charges",
    "surgeon fees": "surgeon_fees",
    "surgeon fee": "surgeon_fees",
    "professional fees": "surgeon_fees",
    "professional fee": "surgeon_fees",
    "pharmacy charges": "pharmacy_charges",
    "pharmacy charge": "pharmacy_charges",
    "pharmacy & medicines": "pharmacy_charges",
    "pharmacy / medicines": "pharmacy_charges",
    "pharmacy/medicines": "pharmacy_charges",
    "pharmacy": "pharmacy_charges",
    "medicines": "pharmacy_charges",
    "medication charges": "pharmacy_charges",
    "g-csf injections": "pharmacy_charges",
    "g-csf injection": "pharmacy_charges",
    "laboratory charges": "laboratory_charges",
    "laboratory charge": "laboratory_charges",
    "laboratory": "laboratory_charges",
    "laboratory tests": "laboratory_charges",
    "lab charges": "laboratory_charges",
    "lab tests": "laboratory_charges",
    "pathology charges": "laboratory_charges",
    "pathology": "laboratory_charges",
    "radiology charges": "radiology_charges",
    "radiology charge": "radiology_charges",
    "radiology & imaging": "radiology_charges",
    "radiology": "radiology_charges",
    "imaging charges": "radiology_charges",
    "investigation charges": "investigation_charges",
    "investigation charge": "investigation_charges",
    "diagnostics & investigations": "investigation_charges",
    "diagnostic charges": "investigation_charges",
    "ecg & monitoring": "investigation_charges",
    "ecg charges": "investigation_charges",
    "ecg monitoring": "investigation_charges",
    "cardiac monitoring": "investigation_charges",
    "monitoring charges": "investigation_charges",
    "nursing charges": "nursing_charges",
    "nursing charge": "nursing_charges",
    "nursing & support services": "nursing_charges",
    "nursing & support": "nursing_charges",
    "nursing": "nursing_charges",
    "consumables": "consumables",
    "consumable": "consumables",
    "medical & surgical consumables": "consumables",
    "surgical consumables": "consumables",
    "implant charges": "consumables",
    "implants": "consumables",
    "ambulance charges": "ambulance_charges",
    "ambulance charge": "ambulance_charges",
    "ambulance": "ambulance_charges",
    "miscellaneous charges": "misc_charges",
    "miscellaneous charge": "misc_charges",
    "miscellaneous": "misc_charges",
    "misc charges": "misc_charges",
    "sundry charges": "misc_charges",
    "dietary services": "misc_charges",
    "dietary charges": "misc_charges",
    "diet charges": "misc_charges",
    "other charges": "other_charges",
    "other charge": "other_charges",
    "physiotherapy charges": "physiotherapy_charges",
    "physiotherapy charge": "physiotherapy_charges",
    "physiotherapy": "physiotherapy_charges",
    "chest physiotherapy": "physiotherapy_charges",
    "blood charges": "blood_charges",
    "blood bank": "blood_charges",
    "blood products": "blood_charges",
    "blood products & bank": "blood_charges",
    "isolation charges": "isolation_charges",
    "isolation ward": "isolation_charges",
    "isolation ward charges": "isolation_charges",
    "transplant charges": "transplant_charges",
    "stem cell charges": "transplant_charges",
    "stem cell / transplant charges": "transplant_charges",
    "stem cell proc.": "transplant_charges",
    "stem cell proc": "transplant_charges",
    "stem cell processing": "transplant_charges",
    "bone marrow": "transplant_charges",
    "chemotherapy charges": "chemotherapy_charges",
    "chemotherapy": "chemotherapy_charges",
    "chemotherapy & conditioning": "chemotherapy_charges",
    "conditioning chemo": "chemotherapy_charges",
    "conditioning chemotherapy": "chemotherapy_charges",
}

# ── KEYWORD FALLBACK (sorted longest-first to avoid partial matches) ──
_EXPENSE_CATEGORY_MAP: Dict[str, str] = {
    "operation theatre": "ot_charges",
    "ot charges": "ot_charges",
    "ot charge": "ot_charges",
    "intensive care": "icu_charges",
    "surgical consumable": "consumables",
    "professional fee": "surgeon_fees",
    "blood bank": "blood_charges",
    "stem cell": "transplant_charges",
    "bone marrow": "transplant_charges",
    "room rent": "room_charges",
    "room charge": "room_charges",
    "hospital services": "nursing_charges",
    "surgeon": "surgeon_fees",
    "procedure": "surgery_charges",
    "surgery": "surgery_charges",
    "surgical": "surgery_charges",
    "anaesthesia": "anaesthesia_charges",
    "anesthesia": "anaesthesia_charges",
    "anaesthetist": "anaesthesia_charges",
    "angio charge": "ot_charges",
    "cath lab": "ot_charges",
    "theatre charge": "ot_charges",
    "consumable": "consumables",
    "consumables": "consumables",
    "implant": "consumables",
    "implants": "consumables",
    "disposable": "consumables",
    "disposables": "consumables",
    "diagnostic": "investigation_charges",
    "diagnostics": "investigation_charges",
    "investigation": "investigation_charges",
    "investigations": "investigation_charges",
    "pathology": "laboratory_charges",
    "radiology": "radiology_charges",
    "imaging": "radiology_charges",
    "x-ray": "radiology_charges",
    "xray": "radiology_charges",
    "endoscopy": "investigation_charges",
    "ecg": "investigation_charges",
    "eeg": "investigation_charges",
    "monitoring": "investigation_charges",
    "cardiac": "investigation_charges",
    "nutrition": "misc_charges",
    "dietary": "misc_charges",
    "laboratory": "laboratory_charges",
    "lab charge": "laboratory_charges",
    "lab test": "laboratory_charges",
    "bed charge": "room_charges",
    "boarding": "room_charges",
    "ward charge": "room_charges",
    "nursing": "nursing_charges",
    "nurse": "nursing_charges",
    "pharmacy": "pharmacy_charges",
    "medication": "pharmacy_charges",
    "medicines": "pharmacy_charges",
    "medicine": "pharmacy_charges",
    "drug": "pharmacy_charges",
    "consultation": "consultation_charges",
    "consultations": "consultation_charges",
    "doctor fee": "consultation_charges",
    "doctor charge": "consultation_charges",
    "physician fee": "consultation_charges",
    "physician charge": "consultation_charges",
    "icu": "icu_charges",
    "hdu": "icu_charges",
    "nicu": "icu_charges",
    "ambulance": "ambulance_charges",
    "miscellaneous": "misc_charges",
    "sundry": "misc_charges",
    "blood product": "blood_charges",
    "blood charge": "blood_charges",
    "platelet": "blood_charges",
    "prbc": "blood_charges",
    "plasma": "blood_charges",
    "haematology": "icu_charges",
    "isolation": "isolation_charges",
    "apheresis": "transplant_charges",
    "transplant": "transplant_charges",
    "chemotherapy": "chemotherapy_charges",
    "chemo": "chemotherapy_charges",
    "melphalan": "chemotherapy_charges",
    "conditioning": "chemotherapy_charges",
    "g-csf": "pharmacy_charges",
    "filgrastim": "pharmacy_charges",
    "injection": "pharmacy_charges",
    "physiotherapy": "physiotherapy_charges",
    "physio": "physiotherapy_charges",
    "dialysis": "other_charges",
    "oxygen": "other_charges",
    "diet": "other_charges",
    "food": "other_charges",
    "laundry": "other_charges",
    "attendant": "other_charges",
    "covid": "other_charges",
    "ppe": "other_charges",
    "registration fee": "other_charges",
    "registration charge": "other_charges",
    "admission fee": "other_charges",
    "admission charge": "other_charges",
    "documentation": "other_charges",
    "admin fee": "other_charges",
    "admin charge": "other_charges",
    "infusion": "other_charges",
    "other charge": "misc_charges",
}


def _categorise_expense(label: str) -> str:
    """Map a free-text expense label to a normalised category.

    Strategy (production-grade, ordered by reliability):
      1. Exact label lookup (highest confidence — handles all common hospital labels)
      2. Longest-keyword-first regex matching (handles partial/noisy labels)
      3. Default to other_charges (safe fallback)
    """
    low = label.lower().strip()
    # Strip leading serial numbers like "1 ", "12 "
    low = re.sub(r"^\d{1,3}\s+", "", low)

    # ── Pass 1: exact match on full label ──
    if low in _EXPENSE_LABEL_EXACT:
        return _EXPENSE_LABEL_EXACT[low]

    # ── Pass 2: prefix keyword match (prevents descriptions from hijacking) ──
    # If a line starts with "Laboratory Bone marrow...", we want "Laboratory" 
    # to win, not "Bone marrow" (which would map to transplant).
    for keyword, category in _EXPENSE_CATEGORY_MAP.items():
        if re.match(rf"^{re.escape(keyword)}\b", low):
            return category

    # ── Pass 3: longest keyword first (prevents "ambulance" in description
    #    from stealing the category when the real label is "Miscellaneous") ──
    best_match: Optional[str] = None
    best_len = 0
    for keyword, category in _EXPENSE_CATEGORY_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", low):
            if len(keyword) > best_len:
                best_len = len(keyword)
                best_match = category

    if best_match:
        return best_match

    return "other_charges"


def _extract_expense_table(
    text: str,
    page_num: int,
    tables: Optional[list[dict[str, Any]]] = None,
    known_cpt_codes: Optional[set[str]] = None,
) -> tuple[list[FieldResult], list[BillingLineItem]]:
    """
    Detect billing / expense sections and parse individual line items.
    
    Parameters
    ----------
    known_cpt_codes : optional set of CPT code strings already extracted for
                      this claim. Any amount that exactly matches a CPT code
                      will be excluded from expense totals.
    """
    _cpt_blacklist = known_cpt_codes or set()

    header_match = _EXPENSE_SECTION_HEADER.search(text)
    if header_match:
        start_idx = text.rfind('\n', 0, header_match.start())
        start_idx = start_idx + 1 if start_idx != -1 else 0
        section_text = text[start_idx:]
    else:
        section_text = text

    table_items: list[tuple[str, str, float]] = []

    # 1. Structural Tables Pass
    if tables:
        for tbl in tables:
            rows = tbl.get("rows") or []
            header = [str(h).strip() for h in (tbl.get("header") or [])]
            if not header and rows:
                header = [str(h).strip() for h in rows[0]]
            
            header_norm = [h.lower() for h in header]
            amount_idx = next((i for i, h in enumerate(header_norm) if "amount" in h), None)
            if amount_idx is None: continue
            label_idx = next((i for i, h in enumerate(header_norm) if any(k in h for k in ("description", "particular", "test", "drug", "expense", "category"))), 0)

            for row in rows[1:]:
                if amount_idx >= len(row): continue
                label = ""
                if label_idx < len(row):
                    label = str(row[label_idx]).strip()
                if not label:
                    label = " ".join(str(c).strip() for i, c in enumerate(row) if i != amount_idx and str(c).strip())
                
                raw_amount = str(row[amount_idx]).strip()
                if not label or not raw_amount: continue
                if re.search(r"(?:total|grand\s*total|sub\s*total|amount\s*payable|sum\s*insured|policy|premium|balance|claimed|requested|exceeding|prev(?:ious)?\s*claims?|limit|period|date| sr\b|\bsl\b|\bsr\.?\s*no)", label, re.I):
                    continue
                
                amount_match = re.search(r"\d[\d,]*\.?\d*", raw_amount)
                if amount_match:
                    try:
                        amt = float(_normalize_amount(amount_match.group(0)))
                        if amt > 0:
                            cat = _categorise_expense(label)
                            table_items.append((label, cat, round(amt, 2)))
                    except: pass

    # 2. Text-based fallback passes — ONLY if structural tables found NOTHING.
    #    IMPORTANT: These are CASCADED — each pass only runs if the previous
    #    found nothing. This prevents the same physical line from being matched
    #    by multiple passes and producing 2×/3× inflated totals.
    if not table_items:
        # Pass 2a: Pipe-delimited lines (e.g., "| Room Charges | Rs. 21,000 |")
        for line in section_text.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < 2:
                continue
            try:
                amt = float(_normalize_amount(cells[-1]))
            except Exception:
                continue
            if amt <= 0:
                continue
            # CPT blacklist: skip if this amount is a known CPT code
            if str(int(amt)) in _cpt_blacklist:
                continue
            lbl_idx = 1 if re.fullmatch(r"\d+", cells[0]) and len(cells) >= 3 else 0
            lbl = cells[lbl_idx]
            if re.search(r"\btotal\b|\bsum\b|\bpolicy\b|\bdate\b|\bsr\b|\bsl\b|\bhead\b|\bamount\b", lbl, re.I):
                continue
            if re.search(
                r"(?:room|board|consult|doctor|physician|pharmacy|medicine|drug|investigation|diagnostic|lab|pathology|radiology|imaging|surge|procedure|operation|ot\b|angio|cath|endoscopy|consumable|disposable|nursing|icu|hdu|nicu|ambulance|misc|sundry|other|anaesth|anesthe|physio|rehabilitation|rehab|dialysis|oxygen|diet|dietary|nutrition|food|registration|admin|attendant|ppe|blood|implant|isolation|transplant|chemo|stem|ecg|eeg|monitoring|cardiac|haematol|hematol|platelet|filgrastim|apheresis|conditioning|g-csf|injection)",
                lbl, re.I,
            ):
                cat = _categorise_expense(lbl)
                table_items.append((lbl, cat, round(amt, 2)))

    if not table_items:
        # Pass 2b: Standard regex — "Room Charges   21,000" (multi-space/tab separated)
        for m in _EXPENSE_LINE.finditer(section_text):
            label, raw_amount = m.groups()
            if re.search(r"\btotal\b|\bsum\b|\bpolicy\b|\bdate\b|\bhead\b|\bamount\b", label, re.I):
                continue
            if not re.search(
                r"(?:room|board|consult|doctor|physician|pharmacy|medication|investigation|diagnostic|lab|pathology|radiology|imaging|surge|procedure|operation|ot\b|angio|cath|endoscopy|consumable|disposable|nursing|icu|hdu|nicu|ambulance|misc|sundry|other|anaesth|anesthe|physio|rehabilitation|rehab|dialysis|oxygen|diet|dietary|nutrition|food|registration|admin|attendant|ppe|blood|implant|isolation|transplant|chemo|stem|ecg|eeg|monitoring|cardiac|haematol|hematol|platelet|filgrastim|apheresis|conditioning|g-csf|injection)",
                label, re.I,
            ):
                continue
            try:
                amt = float(_normalize_amount(raw_amount))
                if amt > 0:
                    # CPT blacklist: skip if this amount is a known CPT code
                    if str(int(amt)) in _cpt_blacklist:
                        continue
                    table_items.append((label, _categorise_expense(label), round(amt, 2)))
            except:
                pass

    if not table_items:
        # Pass 2c: Numbered-line fallback — "1 HDU Charges HDU – 2 Days ... 18,000"
        _NUMBERED_LINE = re.compile(
            r"^\d{1,3}\s+(.+?)\s+(\d[\d,]*\.?\d*)\s*$", re.M
        )
        for m in _NUMBERED_LINE.finditer(section_text):
            full_label, raw_amount = m.groups()
            if re.search(r"\btotal\b|\bsum\b|\bpolicy\b|\bdate\b|\bhead\b|\bamount\b", full_label, re.I):
                continue
            try:
                amt = float(_normalize_amount(raw_amount))
                if amt > 0:
                    # CPT blacklist: skip if this amount is a known CPT code
                    if str(int(amt)) in _cpt_blacklist:
                        continue
                    cat = _categorise_expense(full_label)
                    table_items.append((full_label, cat, round(amt, 2)))
            except:
                pass

    if not table_items:
        # Pass 2d: PaddleOCR parallel lines (Labels on one line, amounts on next few lines)
        lines = section_text.splitlines()
        for i in range(len(lines) - 1):
            lbl_line = lines[i].strip()
            labels = [lbl.strip() for lbl in re.split(r"(?<=\bCHARGES\b)|(?<=\bFEE\b)|(?<=\bFEES\b)", lbl_line, flags=re.I) if lbl.strip()]
            if len(labels) < 2:
                continue
            
            # Scan ahead up to 5 lines for a matching array of numbers
            found_nums = []
            for j in range(1, min(6, len(lines) - i)):
                val_line = lines[i+j]
                
                # Match a sequence of numbers separated ONLY by spaces
                pattern = r"((?:\b\d[\d,]*\.?\d*\b\s+){" + str(len(labels) - 1) + r"}\b\d[\d,]*\.?\d*\b)"
                match = re.search(pattern, val_line)
                if match:
                    nums = [float(_normalize_amount(n)) for n in re.findall(r"\b\d[\d,]*\.?\d*\b", match.group(1))]
                    if len(nums) == len(labels):
                        found_nums = nums
                        break
            
            # Use zip to map the numbers to labels, assuming they are ordered
            if found_nums:
                for j in range(len(labels)):
                    amt = found_nums[j]
                    if str(int(amt)) in _cpt_blacklist:
                        continue
                    cat = _categorise_expense(labels[j])
                    table_items.append((labels[j], cat, round(amt, 2)))

    if not table_items:
        # Pass 2e: Alternating lines (Label on line 1, amount on line 2 or 3)
        lines = section_text.splitlines()
        for i, line in enumerate(lines):
            lbl = line.strip()
            if not re.search(
                r"(?:room|board|consult|doctor|physician|pharmacy|medication|investigation|diagnostic|lab|pathology|radiology|imaging|surge|procedure|operation|ot\b|angio|cath|endoscopy|consumable|disposable|nursing|icu|hdu|nicu|ambulance|misc|sundry|other|anaesth|anesthe|physio|rehabilitation|rehab|dialysis|oxygen|diet|dietary|nutrition|food|registration|admin|attendant|ppe|blood|implant|isolation|transplant|chemo|stem|ecg|eeg|monitoring|cardiac|haematol|hematol|platelet|filgrastim|apheresis|conditioning|g-csf|injection)",
                lbl, re.I,
            ):
                continue
            if re.search(r"\btotal\b|\bsum\b|\bpolicy\b|\bdate\b|\bhead\b|\bamount\b", lbl, re.I):
                continue
            
            for j in range(1, 3):
                if i + j >= len(lines):
                    break
                next_line = lines[i+j].strip()
                clean_line = next_line.replace("{", "")
                nums = [float(_normalize_amount(n)) for n in re.findall(r"\b\d[\d,]*\.?\d*\b", clean_line)]
                nums = [n for n in nums if n > 0]
                if nums:
                    amt = nums[-1]
                    if str(int(amt)) not in _cpt_blacklist:
                        cat = _categorise_expense(lbl)
                        table_items.append((lbl, cat, round(amt, 2)))
                    break

    line_items: list[BillingLineItem] = []
    results: list[FieldResult] = []
    for raw_label, cat, amt in table_items:
        desc = re.sub(r".*\b(?:description|particulars?|details?)\s*[:\-]?\s*", "", raw_label, flags=re.I).strip()
        desc = re.sub(r"^(?:charges?)\s*[:\-]?\s*", "", desc, flags=re.I).strip()
        if not desc:
            desc = cat.replace("_", " ").title()
            
        line_items.append(BillingLineItem(
            description=desc,
            category=cat,
            quantity=1.0,
            unit_price=amt,
            amount=amt
        ))
        results.append(FieldResult(
            # Persist the original bill label so downstream rendering can stay dynamic.
            field_name=desc,
            field_value=f"{amt:.2f}",
            source_page=page_num,
            model_version="expense-table-v5"
        ))

    return results, line_items
