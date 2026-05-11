"""Lightweight layout analyzer — Coordinate-native, region-based.

ARCHITECTURE:
- NO full-page PP-StructureV3 (redundant OCR inside)
- NO LayoutLMv3 (redundant if we have layout routing)
- ONLY use PP-StructureV3 for cropped expense table region (if needed)
- COORDINATE-NATIVE parsing using existing OCR tokens
- ANCHOR-BASED extraction for patient/insurance/diagnosis

This module provides `analyze_layout_lightweight()` which:
1. Analyzes OCR tokens (already extracted) to find sections using coordinates
2. Identifies expense table region using row clustering + coordinate analysis
3. Returns section boundaries WITHOUT running any additional models

Input tokens (canonical):
{
    "text": str,
    "x0": float,
    "y0": float,
    "x1": float,
    "y1": float,
    "page": int
}

Output:
{
  "sections": [
    {
      "type": "patient_info",
      "bbox": [x0, y0, x1, y1],
      "tokens": [...],
      "page": int
    },
    {
      "type": "insurance_info",
      "bbox": [x0, y0, x1, y1],
      "tokens": [...],
      "page": int
    },
    {
      "type": "expense_table",
      "bbox": [x0, y0, x1, y1],
      "tokens": [...],
      "rows": [...],  # Detected from token coordinates
      "page": int
    }
  ]
}

Performance: < 0.5 seconds (no model inference)
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


def token_center(t: Dict[str, Any]) -> Tuple[float, float]:
    """Get center coordinate of token."""
    return ((t["x0"] + t["x1"]) / 2.0, (t["y0"] + t["y1"]) / 2.0)


def token_row_y(t: Dict[str, Any]) -> float:
    """Get vertical center (Y coordinate) of token."""
    return (t["y0"] + t["y1"]) / 2.0


def cluster_rows_by_y(tokens: List[Dict[str, Any]], y_tolerance: float = 8.0) -> List[List[Dict[str, Any]]]:
    """Group tokens into rows by Y coordinate similarity."""
    if not tokens:
        return []
    
    # Sort by vertical position
    sorted_tokens = sorted(tokens, key=token_row_y)
    rows: List[List[Dict[str, Any]]] = []
    
    for token in sorted_tokens:
        token_y = token_row_y(token)
        
        if not rows:
            rows.append([token])
            continue
        
        # Check if token belongs to current row
        current_row = rows[-1]
        avg_row_y = sum(token_row_y(t) for t in current_row) / len(current_row)
        
        if abs(token_y - avg_row_y) <= y_tolerance:
            current_row.append(token)
        else:
            rows.append([token])
    
    return rows


def bbox_for_tokens(tokens: List[Dict[str, Any]]) -> List[float]:
    """Calculate bounding box for a list of tokens."""
    if not tokens:
        return [0, 0, 0, 0]
    x0 = min(t["x0"] for t in tokens)
    y0 = min(t["y0"] for t in tokens)
    x1 = max(t["x1"] for t in tokens)
    y1 = max(t["y1"] for t in tokens)
    return [x0, y0, x1, y1]


def detect_section_anchor(tokens: List[Dict[str, Any]], keywords: List[str]) -> Optional[float]:
    """Find Y coordinate where section starts (first keyword match)."""
    combined_text = " ".join(t.get("text", "").lower() for t in tokens[:50])  # Look at first 50 tokens
    
    for keyword in keywords:
        if keyword.lower() in combined_text:
            # Find the token with this keyword
            for t in tokens:
                if keyword.lower() in t.get("text", "").lower():
                    return token_row_y(t)
    return None


def find_table_region(tokens: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Identify expense table region using coordinate analysis.
    
    Heuristics:
    - Look for rows with expense keywords and numeric amounts
    - Pattern: "Sr. | Label | Description | Amount" with pipe separators
    - Amounts should be currency (Rs., numbers with commas/decimals)
    - Minimum of 2-3 data rows to confirm table
    """
    if not tokens:
        return None
    
    # Build combined text to detect expense table header
    combined_text = " ".join(t.get("text", "") for t in tokens).lower()
    
    # Must have expense breakdown or billing keywords
    has_expense_keywords = any(kw in combined_text for kw in 
        ["expense breakdown", "hospital expense", "hospital bill", "billing", "charges breakdown"])
    
    if not has_expense_keywords:
        return None
    
    # Group into rows by Y coordinate
    rows = cluster_rows_by_y(tokens)
    
    # Look for rows that contain expense amounts (currency patterns)
    # Pattern: Rs. NNNN or plain numbers with thousands separators
    expense_amount_pattern = r"(?:rs\.?\s*[\d,]+(?:\.\d+)?)|(?:\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)"
    table_row_indices = []
    
    for idx, row in enumerate(rows):
        row_text = " ".join(t.get("text", "") for t in row)
        
        # Skip rows that are too short
        if len(row) < 3:
            continue
        
        # Check for amount pattern (Rs. or numeric values with commas)
        has_amount = bool(re.search(expense_amount_pattern, row_text, re.I))
        
        # Check for pipe separator (table structure)
        has_pipe = "|" in row_text
        
        # Row is likely a table row if it has amounts, pipes, or table header terms.
        category_keywords = ["room", "charges", "consultation", "pharmacy", "laboratory", "nursing", 
                           "procedure", "surgery", "consumables", "consumable", "miscellaneous", "ambulance", "icu", "ot"]
        header_keywords = ["sr", "category", "description", "amount", "particular", "expense"]
        has_category = any(kw in row_text.lower() for kw in category_keywords)
        has_header = any(kw in row_text.lower() for kw in header_keywords)

        if (has_amount or has_pipe or has_header) and (has_category or has_header):
            table_row_indices.append(idx)
    
    if len(table_row_indices) < 2:
        return None
    
    # Collect tokens from identified table rows only
    table_tokens = []
    for idx in table_row_indices:
        table_tokens.extend(rows[idx])
    
    if not table_tokens:
        return None
    
    bbox = bbox_for_tokens(table_tokens)
    
    return {
        "type": "expense_table",
        "bbox": bbox,
        "tokens": table_tokens,
        "rows": [
            {
                "tokens": rows[idx],
                "bbox": bbox_for_tokens(rows[idx]),
                "text": " | ".join(t.get("text", "") for t in sorted(rows[idx], key=lambda t: t["x0"]))
            }
            for idx in table_row_indices
        ],
        "row_count": len(table_row_indices),
    }


def analyze_layout_lightweight(
    ocr_tokens: List[Dict[str, Any]],
    page_images: Optional[Dict[int, Any]] = None,
    debug_dump_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze document layout using COORDINATE-NATIVE approach (no models).
    
    Uses existing OCR tokens to detect sections by:
    1. Keyword detection (patient info, insurance, diagnosis, etc.)
    2. Coordinate clustering (identify rows, columns, regions)
    3. Layout heuristics (tables have multiple columns, etc.)
    
    Parameters
    ----------
    ocr_tokens : list of dicts
        Canonical OCR tokens with real geometry (x0, y0, x1, y1, page, text)
    page_images : dict[int, Image], optional
        Ignored (kept for API compatibility with PP-Structure version)
    debug_dump_dir : str, optional
        Directory to write debug artifacts
    
    Returns
    -------
    dict with "sections" key containing detected regions
    
    Performance: < 0.5 seconds (no model inference)
    """
    if not ocr_tokens:
        raise ValueError("analyze_layout_lightweight requires token-level OCR with geometry")
    
    logger.info(f"[LIGHTWEIGHT_LAYOUT] Analyzing {len(ocr_tokens)} tokens (coordinate-native, no models)")
    
    # Group tokens by page
    pages = defaultdict(list)
    for t in ocr_tokens:
        page_no = int(t.get("page", 1))
        pages[page_no].append(t)
    
    result: Dict[str, Any] = {"sections": []}
    
    for page_no, page_tokens in sorted(pages.items()):
        logger.info(f"[LIGHTWEIGHT_LAYOUT] Processing page {page_no} ({len(page_tokens)} tokens)")
        
        if not page_tokens:
            continue
        
        # Get page height range for coordinate-based section detection
        min_y = min(t["y0"] for t in page_tokens)
        max_y = max(t["y1"] for t in page_tokens)
        page_height = max_y - min_y
        
        # 1. Detect patient info section (top of page, contains "patient", "name", "dob")
        # Typically occupies first ~10-15% of page, but search up to 30% to be safe
        patient_threshold = min_y + page_height * 0.35
        patient_tokens = [t for t in page_tokens if t["y1"] < patient_threshold]
        patient_text = " ".join(t.get("text", "").lower() for t in patient_tokens)
        
        if any(kw in patient_text for kw in ["patient", "name", "date of birth", "dob", "age", "gender"]):
            bbox = bbox_for_tokens(patient_tokens)
            result["sections"].append({
                "type": "patient_info",
                "bbox": bbox,
                "tokens": patient_tokens,
                "page": page_no,
            })
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected patient_info on page {page_no}: {len(patient_tokens)} tokens")
        
        # 2. Detect insurance section (after patient, contains "insurance", "policy", "member")
        # Typically at 15-35% of page
        insurance_start = min_y + page_height * 0.25
        insurance_end = min_y + page_height * 0.50
        insurance_tokens = [t for t in page_tokens if insurance_start < t["y0"] < insurance_end]
        insurance_text = " ".join(t.get("text", "").lower() for t in insurance_tokens)
        
        if any(kw in insurance_text for kw in ["insurance", "policy", "member", "subscriber", "payer", "provider"]):
            bbox = bbox_for_tokens(insurance_tokens)
            result["sections"].append({
                "type": "insurance_info",
                "bbox": bbox,
                "tokens": insurance_tokens,
                "page": page_no,
            })
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected insurance_info on page {page_no}: {len(insurance_tokens)} tokens")
        
        # 3. Detect hospitalization section (contains hospital, admission, discharge, doctor, registration)
        hosp_keywords = [
            "hospital name", "registration", "treating doctor", "procedure code",
            "primary diagnosis", "diagnosis", "icd-10", "snomed",
            "type of admission", "ward type", "date of admission", "date of discharge",
            "hospitalization details",
        ]
        hospital_tokens = []
        for row in cluster_rows_by_y(page_tokens):
            row_text = " ".join(t.get("text", "") for t in sorted(row, key=lambda t: t["x0"]))
            if any(kw in row_text.lower() for kw in hosp_keywords):
                hospital_tokens.extend(row)

        if hospital_tokens:
            bbox = bbox_for_tokens(hospital_tokens)
            result["sections"].append({
                "type": "hospitalization_info",
                "bbox": bbox,
                "tokens": hospital_tokens,
                "page": page_no,
            })
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected hospitalization_info on page {page_no}: {len(hospital_tokens)} tokens")
        
        # 4. Detect diagnosis section (keywords: diagnosis, icd, snomed, medical condition)
        # Typically at 30-50% of page
        diagnosis_start = min_y + page_height * 0.30
        diagnosis_end = min_y + page_height * 0.55
        diagnosis_tokens = [t for t in page_tokens if diagnosis_start < t["y0"] < diagnosis_end]
        diagnosis_text = " ".join(t.get("text", "").lower() for t in diagnosis_tokens)
        
        if any(kw in diagnosis_text for kw in ["diagnosis", "icd", "snomed", "medical condition", "reason", "primary diagnosis", "procedure"]):
            bbox = bbox_for_tokens(diagnosis_tokens)
            result["sections"].append({
                "type": "diagnosis",
                "bbox": bbox,
                "tokens": diagnosis_tokens,
                "page": page_no,
            })
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected diagnosis on page {page_no}: {len(diagnosis_tokens)} tokens")
        
        # 5. Detect expense table (contains numeric amounts, keywords: "charge", "amount", "rs", "total")
        # Typically at 40-90% of page
        table_section = find_table_region(page_tokens)
        if table_section:
            table_section["page"] = page_no
            result["sections"].append(table_section)
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected expense_table on page {page_no}")
    
    logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected {len(result['sections'])} sections total (coordinate-native)")
    return result
