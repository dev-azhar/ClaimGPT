from __future__ import annotations

from typing import Any


def classify_document(ocr_pages: list[dict[str, Any]], layout: dict[str, Any] | None = None) -> str:
    sections = (layout or {}).get("sections", []) or []
    section_types = {str(section.get("type", "")).lower() for section in sections}
    combined_text = " ".join(str(page.get("text", "")) for page in ocr_pages).lower()

    if "expense_table" in section_types or "bill_table" in section_types or "table" in section_types:
        return "hospital_bill"
    if any(keyword in combined_text for keyword in ("prescription", "rx", "medication", "medicine")):
        return "prescription"
    if any(keyword in combined_text for keyword in ("lab report", "laboratory", "investigation report", "test result")):
        return "lab_report"
    if any(keyword in combined_text for keyword in ("discharge summary", "final diagnosis", "history of present illness")):
        return "discharge_summary"
    if any(keyword in combined_text for keyword in ("insurance form", "policy number", "member id", "sum insured")):
        return "insurance_form"
    return "hospital_bill"