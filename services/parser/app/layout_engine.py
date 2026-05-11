from __future__ import annotations
import logging
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def cluster_rows_by_y(tokens: List[Dict[str, Any]], y_tolerance: float = 8.0) -> List[List[Dict[str, Any]]]:
    if not tokens:
        return []
    sorted_tokens = sorted(tokens, key=lambda t: (t["y0"] + t["y1"]) / 2.0)
    rows: List[List[Dict[str, Any]]] = []
    for token in sorted_tokens:
        token_y = (token["y0"] + token["y1"]) / 2.0
        if not rows:
            rows.append([token])
            continue
        current_row = rows[-1]
        avg_row_y = sum((t["y0"] + t["y1"]) / 2.0 for t in current_row) / len(current_row)
        if abs(token_y - avg_row_y) <= y_tolerance:
            current_row.append(token)
        else:
            rows.append([token])
    return rows

def bbox_for_tokens(tokens: List[Dict[str, Any]]) -> List[float]:
    if not tokens:
        return [0, 0, 0, 0]
    return [
        min(t["x0"] for t in tokens),
        min(t["y0"] for t in tokens),
        max(t["x1"] for t in tokens),
        max(t["y1"] for t in tokens)
    ]

def extract_regions(ocr_tokens: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not ocr_tokens:
        return {"sections": []}
    
    pages = defaultdict(list)
    for t in ocr_tokens:
        doc_id = t.get("document_id", "default")
        page_no = int(t.get("page", 1))
        pages[(doc_id, page_no)].append(t)
    
    sections = []
    
    for (doc_id, page_no), page_tokens in sorted(pages.items()):
        if not page_tokens:
            continue
            
        min_y = min(t["y0"] for t in page_tokens)
        max_y = max(t["y1"] for t in page_tokens)
        page_height = max_y - min_y
        
        # Patient Info
        patient_tokens = [t for t in page_tokens if t["y1"] < min_y + page_height * 0.35]
        if any(kw in " ".join(t.get("text", "").lower() for t in patient_tokens) for kw in ["patient", "name", "dob", "age", "gender"]):
            sections.append({
                "type": "patient_info",
                "bbox": bbox_for_tokens(patient_tokens),
                "tokens": patient_tokens,
                "page": page_no,
                "document_id": doc_id,
            })
            
        # Diagnosis
        diagnosis_start = min_y + page_height * 0.20
        diagnosis_end = min_y + page_height * 0.60
        diagnosis_tokens = [t for t in page_tokens if diagnosis_start < t["y0"] < diagnosis_end]
        if any(kw in " ".join(t.get("text", "").lower() for t in diagnosis_tokens) for kw in ["diagnosis", "icd", "snomed", "medical condition"]):
            sections.append({
                "type": "diagnosis",
                "bbox": bbox_for_tokens(diagnosis_tokens),
                "tokens": diagnosis_tokens,
                "page": page_no,
                "document_id": doc_id,
            })
            
        # Bill Table
        table_section = _find_bill_table(page_tokens)
        if table_section:
            table_section["page"] = page_no
            table_section["document_id"] = doc_id
            sections.append(table_section)
            
    return {"sections": sections}

def _find_bill_table(tokens: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    rows = cluster_rows_by_y(tokens)
    expense_amount_pattern = r"(?:rs\.?\s*[\d,]+(?:\.\d+)?)|(?:\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b)"
    category_keywords = ["room", "charges", "consultation", "pharmacy", "laboratory", "nursing", "procedure", "surgery", "consumables"]
    header_keywords = ["sr", "category", "description", "amount", "particular", "expense"]
    
    table_row_indices = []
    for idx, row in enumerate(rows):
        if len(row) < 3:
            continue
        row_text = " ".join(t.get("text", "") for t in row).lower()
        has_amount = bool(re.search(expense_amount_pattern, row_text, re.I))
        has_pipe = "|" in row_text
        has_category = any(kw in row_text for kw in category_keywords)
        has_header = any(kw in row_text for kw in header_keywords)
        
        if (has_amount or has_pipe or has_header) and (has_category or has_header):
            table_row_indices.append(idx)
            
    if len(table_row_indices) < 2:
        return None
        
    table_tokens = []
    for idx in table_row_indices:
        table_tokens.extend(rows[idx])
        
    return {
        "type": "bill_table",
        "bbox": bbox_for_tokens(table_tokens),
        "tokens": table_tokens,
        "rows": [{"tokens": rows[idx]} for idx in table_row_indices]
    }
