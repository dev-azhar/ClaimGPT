from __future__ import annotations

from typing import Any

from .form_extractor import extract_form_fields


def parse_discharge_document(layout: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    fields: dict[str, str] = {}
    tables: list[dict[str, Any]] = []

    for section in layout.get("sections", []) or []:
        section_type = str(section.get("type", "")).lower()
        tokens = section.get("tokens", []) or []
        if section_type in {"patient_info", "hospitalization_info", "diagnosis", "key_value", "text", "title"}:
            fields.update(extract_form_fields(tokens))

    return fields, tables