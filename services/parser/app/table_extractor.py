from typing import List, Dict, Any
import re
from collections import defaultdict

MEDICAL_KEYWORDS = ["room", "pharmacy", "consultation", "nursing", "laboratory", "consumables", "procedure", "charges", "delivery", "labour", "oxygen", "special"]


def _cell_text(cell: Any) -> str:
    if isinstance(cell, dict):
        return str(cell.get("text", "")).strip()
    return str(cell).strip()


def _is_numeric_text(value: str) -> bool:
    cleaned = value.replace("Rs.", "").replace("INR", "").replace(",", "").strip()
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _looks_like_header_row(cell_texts: List[str]) -> bool:
    non_empty = [text for text in cell_texts if text]
    if len(non_empty) < 2:
        return False
    if any(_is_numeric_text(text) for text in non_empty):
        return False
    return all(len(text.split()) <= 3 and len(text) <= 24 for text in non_empty)


def extract_table(table_region: Dict[str, Any], table_category: str | None = None) -> List[Dict[str, Any]]:
    """
    Extract structured data from a table region.
    
    Parameters
    ----------
    table_region : dict
        Table region with "rows" or "cells" key
    table_category : str, optional
        Category of table: "expense", "medication", "lab", "vitals", "diagnosis"
        If None, defaults to "expense" for backward compatibility
    
    Returns
    -------
    list of dicts with extracted rows
    """
    if not table_region:
        return []
    
    # Determine category from table_region if not provided
    if not table_category:
        table_category = table_region.get("table_category", "expense")

    # Preserve table structure when the layout analyzer provides a cell grid.
    if table_region.get("cells"):
        if table_category == "medication":
            return _extract_medication_table_from_cells(table_region)
        if table_category == "lab":
            return _extract_lab_table_from_cells(table_region)
        if table_category == "vitals":
            return _extract_vitals_table_from_cells(table_region)
        if table_category == "diagnosis":
            return _extract_diagnosis_table_from_cells(table_region)
        return _extract_expense_table_from_cells(table_region)

    # Route to category-specific extractor
    if table_category == "medication":
        return _extract_medication_table(table_region)
    elif table_category == "lab":
        return _extract_lab_table(table_region)
    elif table_category == "vitals":
        return _extract_vitals_table(table_region)
    elif table_category == "diagnosis":
        return _extract_diagnosis_table(table_region)
    else:
        # Default to expense extraction
        return _extract_expense_table(table_region)


def _extract_expense_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract expense/financial table rows."""
    line_items = []
    
    for row_data in table_region.get("rows", []):
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
        
        tokens = sorted(tokens, key=lambda t: t["x0"])
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        
        # Must contain medical keywords or numeric amount
        has_medical = any(k in row_text for k in MEDICAL_KEYWORDS)
        has_amount = bool(re.search(r"(?:rs\.?\s*[\d,]+(?:\.\d+)?)|(?:\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)", row_text, re.I))
        
        if not (has_medical or has_amount):
            continue
        
        # Skip summary rows
        if re.search(r"\b(?:total|sum insured|claim amount|amount exceeding|grand total)\b", row_text):
            continue
        
        # Find amount (last numeric token)
        amount_val = 0.0
        amount_idx = -1
        
        for i in range(len(tokens) - 1, -1, -1):
            token_text = tokens[i].get("text", "").replace('Rs.', '').replace('INR', '').replace(',', '').strip()
            if token_text.replace('.', '').isdigit():
                try:
                    amount_val = float(token_text)
                    if amount_val > 0:
                        amount_idx = i
                        break
                except ValueError:
                    pass
        
        # Require amount for expense tables
        if amount_idx == -1:
            continue
        
        # Extract description/category
        clean_tokens = [t.get("text", "") for i, t in enumerate(tokens) if i != amount_idx]
        category = clean_tokens[1] if len(clean_tokens) > 1 else "Expense"
        description = " ".join(clean_tokens[2:] or clean_tokens[1:] or [category])
        
        line_items.append({
            "description": description.strip(),
            "category": category.strip(),
            "quantity": 1.0,
            "unit_price": amount_val,
            "amount": amount_val
        })
    
    return line_items


def _extract_expense_table_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    line_items: List[Dict[str, Any]] = []
    rows = table_region.get("cells") or []

    for row_index, row in enumerate(rows):
        cell_texts = [_cell_text(cell) for cell in row]
        non_empty = [text for text in cell_texts if text]
        if not non_empty:
            continue
        if row_index == 0 and _looks_like_header_row(non_empty):
            continue

        amount_value = None
        for text in reversed(cell_texts):
            if _is_numeric_text(text):
                cleaned = text.replace("Rs.", "").replace("INR", "").replace(",", "").strip()
                try:
                    amount_value = float(cleaned)
                    break
                except ValueError:
                    continue

        description = non_empty[0]
        category = description
        if len(non_empty) > 1 and not _is_numeric_text(non_empty[1]):
            category = non_empty[1]
        if amount_value is not None and len(non_empty) > 1 and _is_numeric_text(non_empty[-1]):
            description = " ".join(non_empty[:-1])
            if len(non_empty) > 2 and not _is_numeric_text(non_empty[1]):
                category = non_empty[1]

        line_items.append({
            "description": description.strip() or category.strip() or "Expense",
            "category": category.strip() or description.strip() or "Expense",
            "quantity": 1.0,
            "unit_price": amount_value,
            "amount": amount_value,
            "raw_cells": cell_texts,
            "row_index": row_index,
        })

    return line_items


def _extract_medication_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract medication table rows (medicine, dosage, frequency, days)."""
    medications = []
    columns = table_region.get("columns", [])
    
    for row_data in table_region.get("rows", []):
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
        
        # Skip header rows (usually first row or rows with keywords like "Type", "Drug")
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        if any(kw in row_text for kw in ["type", "drug name", "dosage", "frequency", "sr", "no"]):
            continue
        
        # Extract values by column position
        medicine_name = None
        dosage = None
        frequency = None
        days = None
        instructions = None
        
        for col in columns:
            x0 = col["x0_avg"]
            x1 = col["x1_avg"]
            col_tokens = [t for t in tokens if x0 - 5 <= t["x0"] <= x1 + 5]
            col_text = " ".join(t.get("text", "") for t in sorted(col_tokens, key=lambda t: t["x0"])).strip()
            
            if not col_text:
                continue
            
            col_lower = col_text.lower()
            header = col.get("header_token", "").lower() if col.get("header_token") else ""
            
            # Guess column based on header or content
            if "medicine" in header or "drug" in header or "name" in header or (not header and not medicine_name):
                medicine_name = col_text
            elif "dosage" in header or "dose" in header or "strength" in header:
                dosage = col_text
            elif "frequency" in header or "freq" in header:
                frequency = col_text
            elif "days" in header or "duration" in header:
                days = col_text
            elif "instruction" in header or "instruction" in header:
                instructions = col_text
        
        if medicine_name:
            medications.append({
                "medicine_name": medicine_name,
                "dosage": dosage,
                "frequency": frequency,
                "days": days,
                "instructions": instructions
            })
    
    return medications


def _extract_medication_table_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    medications: List[Dict[str, Any]] = []
    rows = table_region.get("cells") or []

    for row_index, row in enumerate(rows):
        cell_texts = [_cell_text(cell) for cell in row]
        non_empty = [text for text in cell_texts if text]
        if not non_empty:
            continue
        if row_index == 0 and _looks_like_header_row(non_empty):
            continue

        medicine_name = non_empty[0]
        dosage = None
        frequency = None
        days = None
        instructions = None

        numeric_positions = [idx for idx, text in enumerate(cell_texts) if _is_numeric_text(text)]
        if numeric_positions:
            first_numeric = numeric_positions[0]
            dosage = cell_texts[first_numeric]
            trailing = [text for text in cell_texts[first_numeric + 1 :] if text]
            if trailing:
                days = trailing[0]
            if len(trailing) > 1:
                instructions = " ".join(trailing[1:])
        elif len(non_empty) > 1:
            instructions = " ".join(non_empty[1:])

        medications.append({
            "medicine_name": medicine_name,
            "dosage": dosage,
            "frequency": frequency,
            "days": days,
            "instructions": instructions,
            "raw_cells": cell_texts,
            "row_index": row_index,
        })

    return medications


def _extract_lab_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract lab results table rows (test_name, result, units, range)."""
    results = []
    columns = table_region.get("columns", [])
    
    for row_data in table_region.get("rows", []):
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
        
        # Skip header rows
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        if any(kw in row_text for kw in ["test", "result", "units", "range", "normal", "sr", "no"]):
            continue
        
        # Extract by column
        test_name = None
        result = None
        units = None
        range_val = None
        
        for col in columns:
            x0 = col["x0_avg"]
            x1 = col["x1_avg"]
            col_tokens = [t for t in tokens if x0 - 5 <= t["x0"] <= x1 + 5]
            col_text = " ".join(t.get("text", "") for t in sorted(col_tokens, key=lambda t: t["x0"])).strip()
            
            if not col_text:
                continue
            
            header = col.get("header_token", "").lower() if col.get("header_token") else ""
            
            if "test" in header or "name" in header or (not header and not test_name):
                test_name = col_text
            elif "result" in header or "value" in header:
                result = col_text
            elif "unit" in header:
                units = col_text
            elif "range" in header or "normal" in header:
                range_val = col_text
        
        if test_name:
            results.append({
                "test_name": test_name,
                "result": result,
                "units": units,
                "range": range_val
            })
    
    return results


def _extract_lab_table_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    rows = table_region.get("cells") or []

    for row_index, row in enumerate(rows):
        cell_texts = [_cell_text(cell) for cell in row]
        non_empty = [text for text in cell_texts if text]
        if not non_empty:
            continue
        if row_index == 0 and _looks_like_header_row(non_empty):
            continue

        results.append({
            "test_name": non_empty[0] if len(non_empty) > 0 else None,
            "result": non_empty[1] if len(non_empty) > 1 else None,
            "units": non_empty[2] if len(non_empty) > 2 else None,
            "range": non_empty[3] if len(non_empty) > 3 else None,
            "raw_cells": cell_texts,
            "row_index": row_index,
        })

    return results


def _extract_vitals_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract vitals table rows (parameter, value, unit)."""
    vitals = []
    columns = table_region.get("columns", [])
    
    for row_data in table_region.get("rows", []):
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
        
        # Skip header
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        if any(kw in row_text for kw in ["parameter", "value", "unit", "reading", "sr", "no"]):
            continue
        
        # Extract by column
        parameter = None
        value = None
        unit = None
        
        for col in columns:
            x0 = col["x0_avg"]
            x1 = col["x1_avg"]
            col_tokens = [t for t in tokens if x0 - 5 <= t["x0"] <= x1 + 5]
            col_text = " ".join(t.get("text", "") for t in sorted(col_tokens, key=lambda t: t["x0"])).strip()
            
            if not col_text:
                continue
            
            header = col.get("header_token", "").lower() if col.get("header_token") else ""
            
            if "parameter" in header or (not header and not parameter):
                parameter = col_text
            elif "value" in header or "reading" in header:
                value = col_text
            elif "unit" in header:
                unit = col_text
        
        if parameter:
            vitals.append({
                "parameter": parameter,
                "value": value,
                "unit": unit
            })
    
    return vitals


def _extract_vitals_table_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    vitals: List[Dict[str, Any]] = []
    rows = table_region.get("cells") or []

    for row_index, row in enumerate(rows):
        cell_texts = [_cell_text(cell) for cell in row]
        non_empty = [text for text in cell_texts if text]
        if not non_empty:
            continue
        if row_index == 0 and _looks_like_header_row(non_empty):
            continue

        vitals.append({
            "parameter": non_empty[0] if len(non_empty) > 0 else None,
            "value": non_empty[1] if len(non_empty) > 1 else None,
            "unit": non_empty[2] if len(non_empty) > 2 else None,
            "raw_cells": cell_texts,
            "row_index": row_index,
        })

    return vitals


def _extract_diagnosis_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract diagnosis/procedure table rows (diagnosis, icd, procedure, observation)."""
    diagnoses = []
    columns = table_region.get("columns", [])
    
    for row_data in table_region.get("rows", []):
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
        
        # Skip header
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        if any(kw in row_text for kw in ["diagnosis", "icd", "procedure", "observation", "sr", "no"]):
            continue
        
        # Extract by column
        diagnosis = None
        icd_code = None
        procedure = None
        observation = None
        
        for col in columns:
            x0 = col["x0_avg"]
            x1 = col["x1_avg"]
            col_tokens = [t for t in tokens if x0 - 5 <= t["x0"] <= x1 + 5]
            col_text = " ".join(t.get("text", "") for t in sorted(col_tokens, key=lambda t: t["x0"])).strip()
            
            if not col_text:
                continue
            
            header = col.get("header_token", "").lower() if col.get("header_token") else ""
            
            if "diagnosis" in header or (not header and not diagnosis):
                diagnosis = col_text
            elif "icd" in header:
                icd_code = col_text
            elif "procedure" in header:
                procedure = col_text
            elif "observation" in header:
                observation = col_text
        
        if diagnosis:
            diagnoses.append({
                "diagnosis": diagnosis,
                "icd_code": icd_code,
                "procedure": procedure,
                "observation": observation
            })
    
    return diagnoses


def _extract_diagnosis_table_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    diagnoses: List[Dict[str, Any]] = []
    rows = table_region.get("cells") or []

    for row_index, row in enumerate(rows):
        cell_texts = [_cell_text(cell) for cell in row]
        non_empty = [text for text in cell_texts if text]
        if not non_empty:
            continue
        if row_index == 0 and _looks_like_header_row(non_empty):
            continue

        diagnoses.append({
            "diagnosis": non_empty[0] if len(non_empty) > 0 else None,
            "icd_code": non_empty[1] if len(non_empty) > 1 else None,
            "procedure": non_empty[2] if len(non_empty) > 2 else None,
            "observation": non_empty[3] if len(non_empty) > 3 else None,
            "raw_cells": cell_texts,
            "row_index": row_index,
        })

    return diagnoses


def _extract_from_cells(table_region: Dict[str, Any], table_category: str = "expense") -> List[Dict[str, Any]]:
    """Extract from PP-Structure cell grid format."""
    if table_category == "expense":
        return _extract_from_cells_expense(table_region)
    else:
        # For non-expense, just extract all cells
        return _extract_from_cells_generic(table_region)


def _extract_from_cells_expense(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract expense table from cell grid using row structure."""
    cells_grid = table_region.get("cells") or []
    line_items: List[Dict[str, Any]] = []

    for row_index, row in enumerate(cells_grid):
        if not row:
            continue

        cell_texts = []
        for cell in row:
            if isinstance(cell, dict):
                text = str(cell.get("text", "")).strip()
            else:
                text = str(cell).strip()
            cell_texts.append(text)

        if row_index == 0 and _looks_like_header_row(cell_texts):
            continue

        line_items.append({
            "cells": cell_texts,
            "text": " | ".join(cell_texts),
            "row_index": row_index,
        })

    return line_items


def _extract_from_cells_generic(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract generic table from cell grid."""
    cells_grid = table_region.get("cells") or []
    rows = []
    
    for row in cells_grid:
        if not row:
            continue
        
        cell_texts = []
        for cell in row:
            if isinstance(cell, dict):
                text = str(cell.get("text", "")).strip()
            else:
                text = str(cell).strip()
            cell_texts.append(text)
        
        rows.append({
            "cells": cell_texts,
            "text": " | ".join(cell_texts)
        })
    
    return rows
