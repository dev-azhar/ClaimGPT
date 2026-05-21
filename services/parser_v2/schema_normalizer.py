import logging
import re
from typing import List, Dict, Any
from .models import FormField, TableRegion, Region

logger = logging.getLogger("parser-debug")

CANONICAL_MAPPING = {
    "patient_name": "patient_name",
    "patientname": "patient_name",
    "patient_name": "patient_name",
    "name": "patient_name",
    "patient": "patient_name",
    "date_of_birth": "patient_dob",
    "birth_date": "patient_dob",
    "dob": "patient_dob",
    "birth": "patient_dob",
    "age": "patient_age",
    "age_gender": "patient_age",
    "sex": "patient_gender",
    "gender": "patient_gender",
    "address": "patient_address",
    "policy_number": "insurance_policy_number",
    "policy_no": "insurance_policy_number",
    "policy": "insurance_policy_number",
    "claim_no": "claim_number",
    "claim_number": "claim_number",
    "insurance_provider": "insurance_payer",
    "payer": "insurance_payer",
    "provider": "insurance_payer",
    "hospital_name": "hospital_name",
    "hospital": "hospital_name",
    "admission_date": "admission_date",
    "admission": "admission_date",
    "discharge_date": "discharge_date",
    "discharge": "discharge_date",
    "doctor_name": "doctor_name",
    "doctor": "doctor_name",
    "consultant": "doctor_name",
    "diagnosis": "diagnosis",
    "primary_diagnosis": "diagnosis",
    "claimed": "claimed_total",
    "total_claimed": "claimed_total",
    "amount_claimed": "claimed_total",
    "reg": "insurance_policy_number",
    "uid": "patient_id",
    "uhid": "patient_id",
}

def normalize_fields(fields: List[FormField]) -> List[Dict[str, Any]]:
    """Maps geometric fields to canonical schema names."""
    normalized = []
    for field in fields:
        # Strip both colons and hyphens for robust mapping
        key_norm = field.key.lower().strip().replace(":", "").replace("-", "").replace(" ", "_")
        canonical_key = CANONICAL_MAPPING.get(key_norm)
        
        # Semantic disambiguation for "Name"
        if canonical_key == "patient_name" and field.value:
            val_lower = field.value.lower()
            hospital_keywords = ["hospital", "commission", "clinic", "center", "health", "medical center", "pharmacy"]
            if any(kw in val_lower for kw in hospital_keywords) and "ms." not in val_lower and "mr." not in val_lower:
                canonical_key = "hospital_name"

        if canonical_key:
            normalized.append({
                "field": key_norm,
                "canonical_field": canonical_key,
                "value": field.value,
                "confidence": 0.95,
                "bbox": field.value_bbox,
                "page": field.page
            })
    return normalized


def normalize_tables(tables: List[TableRegion]) -> List[Dict[str, Any]]:
    """Identifies and extracts structured expense rows from tables."""
    all_expenses = []
    for table in tables:
        table_kind = getattr(table, "table_kind", None)
        if isinstance(table, dict):
            table_kind = table.get("table_kind", table_kind)

        # Primary gate: explicit expense kinds. Secondary gate: tables that look
        # like itemized billing even when misclassified by reconstructor.
        is_expense_like_kind = bool(table_kind and str(table_kind).lower() in {"expenses", "expense", "expense_table", "bill_table"})

        # Build a header map by inspecting the first few rows (if present).
        rows_list = list(getattr(table, "rows", []) or [])
        header_map = {}
        header_cells = []
        header_texts = []
        # look at the first up-to-3 rows to find a header row with header-like tokens
        for candidate_row in rows_list[:3]:
            candidate_cells = sorted(getattr(candidate_row, "cells", []), key=lambda cell: float(cell.bbox[0]) if getattr(cell, "bbox", None) else 0.0)
            candidate_texts = [str(cell.text or "").strip().lower() for cell in candidate_cells]
            header_like_count = sum(1 for t in candidate_texts if any(term in t for term in ["description", "item", "particular", "service", "drug", "medicine", "qty", "quantity", "rate", "price", "gross", "total", "payable", "net payable", "np"]))
            if header_like_count >= 1:
                header_cells = candidate_cells
                header_texts = candidate_texts
                break

        if header_texts:
            for idx, text in enumerate(header_texts):
                if not text:
                    continue
                if any(term in text for term in ["description", "item", "particular", "service", "drug", "medicine"]):
                    header_map.setdefault("description", idx)
                if any(term in text for term in ["qty", "quantity", "days"]):
                    header_map.setdefault("qty", idx)
                if any(term in text for term in ["rate", "unit price", "price"]):
                    header_map.setdefault("rate", idx)
                if any(term in text for term in ["gross", "total"]):
                    header_map.setdefault("gross", idx)
                if any(term in text for term in ["np", "net payable", "payable", "amount payable", "amt payable", "amount"]):
                    header_map.setdefault("payable", idx)

        is_expense_like_header = bool(header_map and "description" in header_map and ("payable" in header_map or "gross" in header_map or "rate" in header_map))
        
        has_many_numeric_cols = False
        if not (is_expense_like_kind or is_expense_like_header):
            if rows_list and len(rows_list[0].cells) >= 4:
                col_numeric_counts = [0] * len(rows_list[0].cells)
                total_rows = min(5, len(rows_list))
                for r in rows_list[:total_rows]:
                    for i, c in enumerate(r.cells):
                        cleaned = str(c.text or "").replace("Rs.", "").replace("INR", "").replace("₹", "").replace(",", "").strip()
                        if bool(re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned)):
                            col_numeric_counts[i] += 1
                num_numeric_cols = sum(1 for count in col_numeric_counts if count > 0 and count >= (total_rows * 0.4))
                if num_numeric_cols >= 2:
                    has_many_numeric_cols = True

        if not (is_expense_like_kind or is_expense_like_header or has_many_numeric_cols):
            continue

        amount_priority = ["payable", "np", "gross", "rate"]
        qty_x0 = float(header_cells[header_map["qty"]].bbox[0]) if header_cells and "qty" in header_map else None
        category_x0 = float(header_cells[header_map["description"]].bbox[0]) if header_cells and "description" in header_map else None
        amount_header_x0 = {
            name: float(header_cells[idx].bbox[0])
            for name, idx in header_map.items()
            if name in {"payable", "np", "gross", "rate"} and idx < len(header_cells)
        }
        def _looks_numeric(text: str) -> bool:
            cleaned = text.replace("Rs.", "").replace("INR", "").replace("₹", "").replace(",", "").strip()
            return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned))

        def _infer_category(description_lower: str, first_cell_lower: str) -> str:
            if first_cell_lower.startswith(("inj.", "inj", "i.v.", "iv")) or "injection" in description_lower:
                return "Injection"
            if first_cell_lower.startswith(("tab.", "tab", "tablet")) or "tablet" in description_lower:
                return "Tablet"
            if first_cell_lower.startswith(("ns", "rl", "d5", "dns")) or "iv fluid" in description_lower or "normal saline" in description_lower:
                return "Pharmacy"
            if first_cell_lower.startswith(("lab", "lab:")) or any(kw in description_lower for kw in ["lab", "test", "blood", "panel", "investigation", "pathology", "diagnostic"]):
                return "Laboratory"
            if first_cell_lower.startswith(("ot",)) or any(kw in description_lower for kw in ["operation", "surgery", "procedure"]):
                return "Surgery / OT"
            if first_cell_lower.startswith(("usg",)):
                return "USG"
            if first_cell_lower.startswith(("ecg",)):
                return "ECG"
            if first_cell_lower.startswith(("x-ray", "chest")):
                return "X-Ray"
            if first_cell_lower.startswith(("blood",)):
                return "Blood"
            if any(kw in description_lower for kw in ["room", "ward", "icu", "bed", "stay", "accommodation"]):
                return "Room Rent"
            if any(kw in description_lower for kw in ["consultation", "visit", "doctor", "specialist", "cons.", "surgeon", "anaesthesiologist", "fee"]):
                return "Consultation"
            if any(kw in description_lower for kw in ["pharmacy", "medicine", "drug", "iv fluid", "phar", "med."]):
                return "Pharmacy"
            if any(kw in description_lower for kw in ["nursing", "care"]):
                return "Nursing"
            if any(kw in description_lower for kw in ["consumable", "surgical", "glove", "mask", "cons."]):
                return "Consumables"
            if any(kw in description_lower for kw in ["diet", "nutrition"]):
                return "Diet / Nutrition"
            if any(kw in description_lower for kw in ["service", "charge", "tax", "gst", "vat"]):
                return "Service Charges"
            return "Miscellaneous"

        rows_iter = rows_list[1:] if header_map and rows_list else rows_list
        previous_expense = None
        for row in rows_iter:
            if not row.cells:
                continue
                
            cells = sorted(row.cells, key=lambda cell: float(cell.bbox[0]) if getattr(cell, "bbox", None) else 0.0)
            description = ""
            amount = ""
            first_text_cell_lower = ""

            # Continuation line: no numeric values and no serial marker; append to previous description.
            row_text_chunks = [str(cell.text or "").strip() for cell in cells if str(cell.text or "").strip()]
            numeric_cell_count = sum(1 for cell in cells if _looks_numeric(str(cell.text or "").strip()))
            first_cell_text = row_text_chunks[0] if row_text_chunks else ""
            first_cell_is_serial = bool(re.fullmatch(r"\d+", first_cell_text))
            if numeric_cell_count == 0 and row_text_chunks and not first_cell_is_serial and previous_expense is not None:
                previous_expense["description"] = (previous_expense.get("description", "") + " " + " ".join(row_text_chunks)).strip()
                continue

            for cell in cells:
                cell_text = str(cell.text or "").strip()
                if not cell_text:
                    continue
                if _looks_numeric(cell_text):
                    continue
                first_text_cell_lower = cell_text.lower()
                break

            amount_idx = None
            chosen_amount_header = None
            for header_name in amount_priority:
                if header_name in header_map:
                    candidate_x0 = amount_header_x0.get(header_name)
                    if candidate_x0 is None:
                        continue
                    for candidate_idx in range(len(cells) - 1, -1, -1):
                        candidate_cell = cells[candidate_idx]
                        candidate_text = str(candidate_cell.text or "").strip()
                        if not _looks_numeric(candidate_text):
                            continue
                        if float(candidate_cell.bbox[0]) + 1e-3 < candidate_x0:
                            continue
                        amount_idx = candidate_idx
                        chosen_amount_header = header_name
                        break
                    if amount_idx is not None:
                        break

            if amount_idx is None:
                for i in range(len(cells) - 1, -1, -1):
                    if _looks_numeric(cells[i].text):
                        amount_idx = i
                        break

            if amount_idx is not None:
                amount = cells[amount_idx].text
                description_parts = []
                
                # If there's no header to give us qty_x0, we can infer the end of the description
                # by finding the last non-numeric cell. All subsequent numeric cells are assumed
                # to be quantity, rate, amount columns.
                last_desc_idx = len(cells) - 1
                if qty_x0 is None:
                    for i in range(len(cells) - 1, -1, -1):
                        if not _looks_numeric(str(cells[i].text or "")):
                            last_desc_idx = i
                            break

                for idx_c, cell in enumerate(cells):
                    cell_x0 = float(cell.bbox[0]) if getattr(cell, "bbox", None) else 0.0
                    cell_text = str(cell.text or "").strip()
                    if not cell_text:
                        continue
                    if _looks_numeric(cell_text) and not description_parts:
                        continue
                    if qty_x0 is not None and cell_x0 >= qty_x0 - 1e-3:
                        continue
                    if qty_x0 is None and idx_c > last_desc_idx:
                        continue
                    description_parts.append(cell_text)
                description = " ".join(description_parts).strip()

            if not description or not amount:
                continue

            if description and amount:
                desc_lower = description.lower()
                # Reject insurance / summary metadata that is not an itemized expense
                # Stronger blacklist to avoid patient metadata being treated as expenses
                blacklist = [
                    "h.no",
                    "gstin",
                    "bill no",
                    "bill number",
                    "claim no",
                    "claim number",
                    "auth",
                    "invoice",
                    "summary",
                    "total",
                    "total amount",
                    "total claimed",
                    "sum insured",
                    "requested",
                    "claim amount",
                    "amount requested",
                    "claim requested",
                    "code",
                    "procedure code",
                    "icd-10",
                    "snomed",
                    "date of birth",
                    "dob",
                    "age:",
                    "age",
                    "phone",
                    "email",
                    "address",
                    "hospital name",
                    "patient name",
                ]
                if any(kw in desc_lower for kw in blacklist):
                    continue

                # Validate extracted amount is numeric and not a date or text blob
                if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", amount):
                    # amount looks like a date -> skip
                    continue
                # extract numeric portion
                amt_clean = re.sub(r"[^0-9\.\-]", "", amount)
                if not re.match(r"^-?\d+(?:\.\d+)?$", amt_clean):
                    continue

                first_cell_lower = first_text_cell_lower or (str(cells[0].text or "").strip().lower() if cells else "")
                category = _infer_category(desc_lower, first_cell_lower)

                all_expenses.append({
                    "field_name": description,
                    "description": description,
                    "payable_amount": amount,
                    "amount": amount,
                    "category": category,
                    "page": table.rows[0].cells[0].tokens[0].page if table.rows[0].cells and table.rows[0].cells[0].tokens else 1
                })
                previous_expense = all_expenses[-1]
                
    return all_expenses


def normalize_region_expenses(regions: List[Region]) -> List[Dict[str, Any]]:
    """Extract itemized expenses from non-table OCR regions."""
    expenses: List[Dict[str, Any]] = []
    blacklist = [
        "patient name",
        "age/gender",
        "admission date",
        "discharge date",
        "consultant",
        "claim no",
        "uhid",
        "hospital",
        "diagnosis",
        "gross total",
        "sum insured",
        "previous claims",
        "claim vs sum insured",
        "amount exceeding policy",
        "risk factor",
        "policy status",
        "icd-10",
        "snomed",
        "claim amount",
        "amount requested",
        "claim requested",
        "total claimed",
        "gross total",
        "total bill amount",
        "admissible amount",
        "patient share",
        "co-pay",
        "subtotal",
        "net payable",
        "claim(s)",
        "code:",
        "procedure code",
        "icd-10",
        "snomed",
    ]

    for region in regions:
        region_type = str(getattr(region, "region_type", "")).lower()
        if region_type not in {"patient_form", "text", "paragraph", "title"}:
            continue

        tokens = sorted(getattr(region, "tokens", []) or [], key=lambda t: getattr(t, "x0", 0.0))
        if len(tokens) < 2:
            continue

        row_text = " ".join(getattr(t, "text", "").strip() for t in tokens if getattr(t, "text", "").strip())
        row_lower = row_text.lower()
        if any(term in row_lower for term in blacklist):
            continue

        amount_idx = -1
        amount_text = ""
        for idx in range(len(tokens) - 1, -1, -1):
            token_text = getattr(tokens[idx], "text", "").replace("Rs.", "").replace("INR", "").replace(",", "").strip()
            if not token_text:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", token_text):
                amount_idx = idx
                amount_text = getattr(tokens[idx], "text", "").strip()
                break

        if amount_idx <= 0 or not amount_text:
            continue

        description = " ".join(getattr(t, "text", "").strip() for t in tokens[:amount_idx] if getattr(t, "text", "").strip())
        desc_lower = description.lower().strip()
        if not description or any(term in desc_lower for term in blacklist):
            continue

        # Skip lines that are clearly patient metadata
        if re.search(r"date of birth|dob|phone:|email:|address:|age:\b", description, flags=re.I):
            continue

        category = "Miscellaneous"
        if any(kw in desc_lower for kw in ["room", "ward", "icu", "bed", "stay", "accommodation"]):
            category = "Room Rent"
        elif any(kw in desc_lower for kw in ["consultation", "visit", "doctor", "specialist", "cons."]):
            category = "Consultation"
        elif any(kw in desc_lower for kw in ["pharmacy", "medicine", "drug", "iv fluid", "phar", "med."]):
            category = "Pharmacy"
        elif any(kw in desc_lower for kw in ["lab", "test", "blood", "panel", "investigation", "pathology", "diagnostic"]):
            category = "Laboratory"
        elif any(kw in desc_lower for kw in ["procedure", "surgery", "operation", "injection", "treatment", "proc.", "package"]):
            category = "Procedure"
        elif any(kw in desc_lower for kw in ["nursing", "care"]):
            category = "Nursing"
        elif any(kw in desc_lower for kw in ["consumable", "surgical", "glove", "mask", "cons."]):
            category = "Consumables"
        elif any(kw in desc_lower for kw in ["service", "charge", "tax", "gst", "vat"]):
            category = "Service Charges"

        # Validate amount looks numeric (reject dates or non-numeric tokens)
        amt_clean = re.sub(r"[^0-9\.\\-]", "", amount_text)
        if not re.match(r"^-?\d+(?:\.\d+)?$", amt_clean):
            continue

        expenses.append({
            "description": description,
            "amount": amount_text,
            "category": category,
            "page": getattr(region, "page", 1),
        })

    return expenses


def normalize_summary_bill_expenses(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract expense rows from package / billing summary documents.

    These documents often present a label list on the left and amounts on the right,
    followed by total / admissible / patient-share summary rows. This function
    recovers the charge rows directly from OCR tokens and ignores summary totals.
    """
    if not tokens:
        return []

    document_text = " ".join(str(token.get("text", "")).strip() for token in tokens if str(token.get("text", "")).strip()).lower()
    summary_markers = ["package billing summary", "gross total", "admissible amount", "patient share", "co-pay"]
    if not any(marker in document_text for marker in summary_markers):
        return []

    expense_keywords = [
        "room",
        "ward",
        "nursing",
        "inj.",
        "inj",
        "injection",
        "tab.",
        "tab",
        "tablet",
        "consultation",
        "doctor",
        "specialist",
        "surgery",
        "surgical",
        "procedure",
        "package",
        "pharmacy",
        "medicine",
        "drug",
        "diagnostic",
        "diagnostics",
        "lab",
        "laboratory",
        "test",
        "investigation",
        "pathology",
        "consumable",
        "consumables",
        "miscellaneous",
        "service",
        "charge",
    ]
    summary_blacklist = [
        "h.no",
        "gstin",
        "bill no",
        "bill number",
        "total claimed",
        "gross total",
        "total bill amount",
        "admissible amount",
        "patient share",
        "co-pay",
        "net payable",
        "subtotal",
        "less:",
        "claim no",
        "policy",
        "uhid",
        "patient name",
        "hospital name",
        "admission date",
        "discharge date",
        "diagnosis",
        "consultant",
        "claim(s)",
        "code:",
        "procedure code",
        "icd-10",
        "snomed",
    ]

    def _line_center_y(line_tokens: List[Dict[str, Any]]) -> float:
        values = []
        for token in line_tokens:
            try:
                values.append((float(token.get("y0", 0.0)) + float(token.get("y1", 0.0))) / 2.0)
            except Exception:
                continue
        return sum(values) / len(values) if values else 0.0

    sorted_tokens = sorted(
        [token for token in tokens if str(token.get("text", "")).strip()],
        key=lambda token: (int(token.get("page", 1)), float(token.get("y0", 0.0)), float(token.get("x0", 0.0))),
    )

    lines: list[dict[str, Any]] = []
    y_tolerance = 5.5
    for token in sorted_tokens:
        page = int(token.get("page", 1))
        token_y = (float(token.get("y0", 0.0)) + float(token.get("y1", 0.0))) / 2.0
        if not lines or lines[-1]["page"] != page or abs(token_y - lines[-1]["center_y"]) > y_tolerance:
            lines.append({"page": page, "center_y": token_y, "tokens": [token]})
        else:
            lines[-1]["tokens"].append(token)
            lines[-1]["center_y"] = _line_center_y(lines[-1]["tokens"])

    summary_expenses: List[Dict[str, Any]] = []
    seen_rows: set[tuple[str, str, int]] = set()

    for line in lines:
        line_tokens = sorted(line["tokens"], key=lambda token: float(token.get("x0", 0.0)))
        line_text = " ".join(str(token.get("text", "")).strip() for token in line_tokens if str(token.get("text", "")).strip())
        line_lower = line_text.lower()

        if not any(keyword in line_lower for keyword in expense_keywords):
            continue
        if any(term in line_lower for term in summary_blacklist):
            continue

        amount_index = -1
        amount_text = ""
        for idx in range(len(line_tokens) - 1, -1, -1):
            token_text = str(line_tokens[idx].get("text", "")).replace("Rs.", "").replace("INR", "").replace(",", "").strip()
            if not token_text:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", token_text):
                amount_index = idx
                amount_text = str(line_tokens[idx].get("text", "")).strip()
                break

        if amount_index <= 0 or not amount_text:
            continue

        if amount_text.replace(",", "").isdigit() and len(amount_text.replace(",", "")) >= 7:
            if any(term in line_lower for term in {"code", "procedure code", "icd-10", "snomed"}):
                continue

        description_end = amount_index
        if amount_index > 0:
            previous_text = str(line_tokens[amount_index - 1].get("text", "")).strip().lower()
            if previous_text in {"rs.", "rs", "inr", "₹"}:
                description_end = amount_index - 1

        description = " ".join(str(token.get("text", "")).strip() for token in line_tokens[:description_end] if str(token.get("text", "")).strip())
        # Strip leading serial number from numbered bill rows (e.g. "1 Room Charges ...").
        description = re.sub(r"^\s*\d+\s+", "", description).strip()

        # Strip trailing numeric table columns accidentally included in description
        # (qty/rate/gross/np) when row reconstruction is noisy.
        desc_parts = description.split()
        while desc_parts and re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", desc_parts[-1].replace("₹", "").replace("Rs.", "").replace("rs.", "")):
            desc_parts.pop()
        description = " ".join(desc_parts).strip()

        description_lower = description.lower().strip()
        if not description or any(term in description_lower for term in summary_blacklist):
            continue

        category = "Miscellaneous"
        if description_lower.startswith(("inj.", "inj ", "injection")):
            category = "Injection"
        elif description_lower.startswith(("tab.", "tab ", "tablet")):
            category = "Tablet"
        if any(kw in description_lower for kw in ["room", "ward", "icu", "bed", "stay", "accommodation"]):
            category = "Room Rent"
        elif any(kw in description_lower for kw in ["consultation", "visit", "doctor", "specialist", "cons."]):
            category = "Consultation"
        elif any(kw in description_lower for kw in ["pharmacy", "medicine", "drug", "iv fluid", "phar", "med."]):
            category = "Pharmacy"
        elif any(kw in description_lower for kw in ["lab", "test", "blood", "panel", "investigation", "pathology", "diagnostic"]):
            category = "Laboratory"
        elif any(kw in description_lower for kw in ["procedure", "surgery", "operation", "injection", "treatment", "proc.", "package"]):
            category = "Procedure"
        elif any(kw in description_lower for kw in ["nursing", "care"]):
            category = "Nursing"
        elif any(kw in description_lower for kw in ["consumable", "surgical", "glove", "mask", "cons."]):
            category = "Consumables"
        elif any(kw in description_lower for kw in ["service", "charge", "tax", "gst", "vat"]):
            category = "Service Charges"

        key = (description_lower, amount_text.lower(), int(line.get("page", 1)))
        if key in seen_rows:
            continue
        seen_rows.add(key)

        summary_expenses.append({
            "description": description,
            "amount": amount_text,
            "category": category,
            "page": int(line.get("page", 1)),
        })

    return summary_expenses


def normalize_table_fields(tables: List[TableRegion]) -> List[Dict[str, Any]]:
    """Extract form-like fields from non-expense tables."""
    normalized: List[Dict[str, Any]] = []

    label_aliases = [
        "patient name",
        "age/gender",
        "age gender",
        "admission date",
        "discharge date",
        "diagnosis",
        "consultant",
        "claim no",
        "claim number",
        "uhid",
        "hospital name",
        "doctor",
        "address",
        "policy",
        "policy number",
        "member id",
        "date of birth",
        "dob",
    ]
    label_aliases = sorted(label_aliases, key=len, reverse=True)

    def _canonicalize_label(label_text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", label_text.lower()).strip("_")

    for table in tables:
        table_kind = getattr(table, "table_kind", None)
        if isinstance(table, dict):
            table_kind = table.get("table_kind", table_kind)

        if table_kind and str(table_kind).lower() in {"expenses", "expense", "expense_table", "bill_table"}:
            continue

        for row in table.rows:
            if not row.cells:
                continue

            cells = row.cells
            row_text = " ".join((cell.text or "").strip() for cell in cells if (cell.text or "").strip())
            row_lower = row_text.lower()
            matches: list[tuple[int, int, str]] = []
            for alias in label_aliases:
                match = re.search(rf"(?<!\w){re.escape(alias)}(?=\s*:|\b)", row_lower)
                if match:
                    matches.append((match.start(), match.end(), alias))

            if not matches:
                continue

            matches.sort(key=lambda item: item[0])
            for idx, (start, end, alias) in enumerate(matches):
                value_start = end
                value_end = matches[idx + 1][0] if idx + 1 < len(matches) else len(row_text)
                value = row_text[value_start:value_end].strip()
                value = value.lstrip(":-|").strip()
                if not value:
                    continue

                key_norm = _canonicalize_label(alias)
                bbox = row.cells[0].bbox if row.cells else [0, 0, 0, 0]

                if key_norm in {"age_gender", "agegender"}:
                    parts = [p.strip() for p in re.split(r"[/|,]", value) if p.strip()]
                    if parts:
                        normalized.append({
                            "field": "age",
                            "canonical_field": "patient_age",
                            "value": parts[0],
                            "confidence": 0.9,
                            "bbox": bbox,
                            "page": table.page,
                        })
                    if len(parts) > 1:
                        normalized.append({
                            "field": "gender",
                            "canonical_field": "patient_gender",
                            "value": parts[1],
                            "confidence": 0.9,
                            "bbox": bbox,
                            "page": table.page,
                        })
                    continue

                canonical_key = CANONICAL_MAPPING.get(key_norm)
                if canonical_key:
                    normalized.append({
                        "field": key_norm,
                        "canonical_field": canonical_key,
                        "value": value,
                        "confidence": 0.9,
                        "bbox": bbox,
                        "page": table.page,
                    })

    return normalized
