from __future__ import annotations

from typing import Any

from .form_extractor import extract_form_fields
from .table_extractor import extract_table


def parse_bill_document(layout: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    fields: dict[str, str] = {}
    tables: list[dict[str, Any]] = []
    line_items: list[dict[str, Any]] = []

    for section in layout.get("sections", []) or []:
        section_type = str(section.get("type", "")).lower()
        tokens = section.get("tokens", []) or []

        if section_type in {"patient_info", "insurance_info", "hospitalization_info", "diagnosis", "key_value", "text", "title"}:
            fields.update(extract_form_fields(tokens))

        # Handle both old format (expense_table) and new format (generic_table)
        if section_type in {"expense_table", "bill_table", "table"}:
            items = extract_table(section, table_category="expense")
            if items:
                line_items.extend(items)
        elif section_type == "generic_table":
            table_category = section.get("table_category") or "expense"
            if table_category == "expense":
                items = extract_table(section, table_category="expense")
                if items:
                    line_items.extend(items)

    if line_items:
        tables.append({
            "type": "expenses",
            "source_page": (layout.get("sections", []) or [{}])[0].get("page"),
            "header": ["description", "category", "quantity", "unit_price", "amount"],
            "rows": [[item["description"], item["category"], item["quantity"], item["unit_price"], item["amount"]] for item in line_items],
            "structured_rows": line_items,
            "row_count": len(line_items),
        })

    return fields, tables, line_items