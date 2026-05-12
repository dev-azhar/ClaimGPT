from __future__ import annotations

from typing import Any

from .form_extractor import extract_form_fields
from .table_extractor import extract_table


def parse_lab_document(layout: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """
    Parse laboratory report document.
    
    Extracts:
    - Form fields: patient info, lab info, test date, etc.
    - Lab results tables
    
    Parameters
    ----------
    layout : dict
        Layout with sections from lightweight analyzer
    
    Returns
    -------
    tuple of (fields, tables)
        fields: dict of extracted form fields
        tables: list of tables including lab_results
    """
    fields: dict[str, str] = {}
    tables: list[dict[str, Any]] = []
    lab_results: list[dict[str, Any]] = []

    for section in layout.get("sections", []) or []:
        section_type = str(section.get("type", "")).lower()
        tokens = section.get("tokens", []) or []
        
        if section_type in {"patient_info", "lab_info", "key_value", "text", "title"}:
            fields.update(extract_form_fields(tokens))
        
        # Extract lab results tables from generic_table sections
        elif section_type == "generic_table":
            table_category = section.get("table_category")
            if table_category == "lab":
                items = extract_table(section, table_category="lab")
                if items:
                    lab_results.extend(items)
    
    # Structure lab results as a table
    if lab_results:
        tables.append({
            "type": "lab_results",
            "source_page": layout.get("sections", [{}])[0].get("page"),
            "rows": lab_results,
            "row_count": len(lab_results),
        })

    return fields, tables
