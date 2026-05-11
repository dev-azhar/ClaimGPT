from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict

from .layout_engine import extract_regions
from .form_extractor import extract_form_fields
from .table_extractor import extract_table

logger = logging.getLogger("parser.engine")

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
    
def parse_document(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[Any] = None,
    layout: Optional[Dict[str, Any]] = None,
) -> ParseOutput:
    logger.info("Running NEW ARCHITECTURE parser pipeline")
    
    # 1. Extract all tokens from all pages
    all_tokens = []
    for page in ocr_pages:
        page_num = page.get("page_number", 1)
        doc_id = page.get("document_id")
        for t in page.get("tokens", []):
            if "page" not in t:
                t["page"] = page_num
            t["document_id"] = doc_id
            all_tokens.append(t)
            
    # 2. Layout Engine (Regions only)
    layout_regions = extract_regions(all_tokens)
    
    # 3. Form Extractor
    form_data = {}
    patient_info_regions = [r for r in layout_regions["sections"] if r["type"] == "patient_info"]
    for region in patient_info_regions:
        fields = extract_form_fields(region.get("tokens", []))
        form_data.update(fields)
        
    # 4. Table Extractor
    table_data = []
    bill_table_regions = [r for r in layout_regions["sections"] if r["type"] == "bill_table"]
    extracted_tables = []
    for region in bill_table_regions:
        line_items = extract_table(region)
        if line_items:
            table_data.extend(line_items)
            extracted_tables.append({
                "source_page": region.get("page"),
                "header": ["description", "category", "quantity", "unit_price", "amount"],
                "rows": [[item["description"], item["category"], item["quantity"], item["unit_price"], item["amount"]] for item in line_items],
                "row_count": len(line_items),
            })
            
    import json
    # Convert form data to FieldResults
    field_results = []
    for key, val in form_data.items():
        if val:
            field_results.append(FieldResult(
                field_name=key,
                field_value=val,
                model_version="form-extractor-v1"
            ))
            
    # Add table data as JSON fields
    for i, item in enumerate(table_data):
        field_results.append(FieldResult(
            field_name=f"expense_table_row_{i+1}",
            field_value=json.dumps({"category": item["category"], "amount": item["amount"], "description": item["description"]}),
            model_version="expense-table-modular"
        ))
            
    return ParseOutput(
        fields=field_results,
        tables=extracted_tables,
        sections=layout_regions["sections"],
        page_objects=ocr_pages,
        used_fallback=False,
        model_version="modular-parser-v1"
    )
