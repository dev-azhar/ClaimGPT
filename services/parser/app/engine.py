from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pydantic import BaseModel
from typing import Literal
from typing import Any, Optional, List, Dict

from .bill_parser import parse_bill_document
from .document_classifier import classify_document
from .discharge_parser import parse_discharge_document
from .prescription_parser import parse_prescription_document
from .lab_parser import parse_lab_document
from .form_extractor import extract_form_fields

logger = logging.getLogger("parser.engine")


# Backwards-compatible Pydantic model expected by VLM and other callers.
class StructuredClaimExtraction(BaseModel):
    patient_name: str | None = None
    member_id: str | None = None
    policy_number: str | None = None
    age: int | None = None
    hospital_name: str | None = None
    admission_date: str | None = None
    discharge_date: str | None = None
    primary_diagnosis: str | None = None
    secondary_diagnosis: str | None = None
    procedures: list[str] = []
    treating_doctor: str | None = None
    claimed_total: float | None = None
    bill_line_items: list[dict] = []
    notes: str | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"] | None = None


@dataclass
class FieldResult:
    field_name: str
    field_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    source_page: int | None = None
    model_version: str | None = None
    document_id: str | None = None
    doc_type: str | None = None
    confidence: float | None = None
    extractor_name: str | None = None
    provenance: dict | None = None

@dataclass
class ParseOutput:
    fields: list[FieldResult] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    page_objects: list[dict[str, Any]] = field(default_factory=list)
    document_boundaries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    model_version: str | None = None
    used_fallback: bool = False
    
def parse_document(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[Any] = None,
    layout: Optional[Dict[str, Any]] = None,
) -> ParseOutput:
    logger.info("Running layout-driven parser pipeline")

    if not layout or not layout.get("sections"):
        raise ValueError("parse_document requires a layout payload with sections")

    document_type = classify_document(ocr_pages, layout)
    sections = layout.get("sections", []) or []

    if document_type == "hospital_bill":
        form_data, tables, line_items = parse_bill_document(layout)
    elif document_type == "discharge_summary":
        form_data, tables = parse_discharge_document(layout)
        line_items = []
    elif document_type == "prescription":
        form_data, tables = parse_prescription_document(layout)
        line_items = []
    elif document_type == "lab_report":
        form_data, tables = parse_lab_document(layout)
        line_items = []
    else:
        form_data, tables = parse_discharge_document(layout)
        line_items = []

    import json

    field_results: list[FieldResult] = []
    for key, val in form_data.items():
        if val:
            field_results.append(FieldResult(
                field_name=key,
                field_value=val,
                model_version=f"{document_type}-form-v1",
            ))

    for i, item in enumerate(line_items):
        field_results.append(FieldResult(
            field_name=f"expense_table_row_{i+1}",
            field_value=json.dumps({"category": item["category"], "amount": item["amount"], "description": item["description"]}),
            model_version=f"{document_type}-expense-table-v1",
        ))

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
        fields=field_results,
        tables=tables,
        sections=sections,
        page_objects=ocr_pages,
        used_fallback=False,
        model_version=f"{document_type}-pp-structure-v1",
    )
