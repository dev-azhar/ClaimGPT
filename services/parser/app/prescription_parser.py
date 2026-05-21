from __future__ import annotations

from typing import Any

from .form_extractor import extract_form_fields
from .table_extractor import extract_table


def parse_prescription_document(layout: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    fields: dict[str, str] = {}
    tables: list[dict[str, Any]] = []
    medications: list[dict[str, Any]] = []

    for section in layout.get("sections", []) or []:
        section_type = str(section.get("type", "")).lower()
        tokens = section.get("tokens", []) or []
        
        if section_type in {"patient_info", "insurance_info", "key_value", "text", "title"}:
            fields.update(extract_form_fields(tokens))
        
        # Extract medication tables from generic_table sections
        elif section_type == "generic_table":
            table_category = section.get("table_category")
            if table_category == "medication":
                items = extract_table(section, table_category="medication")
                if items:
                    medications.extend(items)
    
    # Structure medications as a table for consistency
    if medications:
        tables.append({
            "type": "medications",
            "source_page": layout.get("sections", [{}])[0].get("page"),
            "rows": medications,
            "row_count": len(medications),
        })

    return fields, tables