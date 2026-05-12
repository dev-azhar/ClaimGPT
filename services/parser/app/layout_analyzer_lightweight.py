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


def classify_table_category(row_text: str) -> Optional[str]:
    """Classify table category based on row content keywords."""
    row_lower = row_text.lower()
    
    # Medication table indicators
    medication_keywords = ["tab", "cap", "inj", "medicine", "drug", "dosage", "frequency", "days", "dose", "qunt", "instruction"]
    if sum(1 for kw in medication_keywords if kw in row_lower) >= 2:
        return "medication"
    
    # Lab table indicators
    lab_keywords = ["test", "result", "units", "range", "investigation", "lab", "laboratory", "normal", "abnormal"]
    if sum(1 for kw in lab_keywords if kw in row_lower) >= 2:
        return "lab"
    
    # Vitals table indicators
    vitals_keywords = ["bp", "pulse", "temp", "spo2", "temperature", "pressure", "heart rate", "respiratory"]
    if sum(1 for kw in vitals_keywords if kw in row_lower) >= 2:
        return "vitals"
    
    # Diagnosis/procedure table indicators
    diagnosis_keywords = ["diagnosis", "icd", "procedure", "observation", "finding"]
    if sum(1 for kw in diagnosis_keywords if kw in row_lower) >= 2:
        return "diagnosis"
    
    # Expense table indicators
    expense_keywords = ["room", "charges", "consultation", "pharmacy", "laboratory", "nursing", "procedure", "surgery", "consumables"]
    if sum(1 for kw in expense_keywords if kw in row_lower) >= 1:
        return "expense"
    
    return None


def _token_x_center(token: Dict[str, Any]) -> float:
    return (float(token["x0"]) + float(token["x1"])) / 2.0


def _cluster_columns_by_x(tokens: List[Dict[str, Any]], x_tolerance: float = 28.0) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    for token in sorted(tokens, key=_token_x_center):
        center = _token_x_center(token)
        matched = None
        for cluster in clusters:
            if abs(center - cluster["center"]) <= x_tolerance:
                matched = cluster
                break

        if matched is None:
            clusters.append({"center": center, "tokens": [token]})
        else:
            matched["tokens"].append(token)
            matched["center"] = sum(_token_x_center(t) for t in matched["tokens"]) / len(matched["tokens"])

    columns: List[Dict[str, Any]] = []
    for index, cluster in enumerate(sorted(clusters, key=lambda c: c["center"])):
        cluster_tokens = sorted(cluster["tokens"], key=lambda t: t["x0"])
        columns.append({
            "x0_avg": min(t["x0"] for t in cluster_tokens),
            "x1_avg": max(t["x1"] for t in cluster_tokens),
            "x_center": cluster["center"],
            "header_token": cluster_tokens[0].get("text") if cluster_tokens else None,
            "column_index": index,
        })
    return columns


def _build_table_cells(table_candidate_rows: List[List[Dict[str, Any]]], columns: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    table_cells: List[List[Dict[str, Any]]] = []
    for row in table_candidate_rows:
        row_cells: List[List[Dict[str, Any]]] = [[] for _ in columns]
        for token in sorted(row, key=_token_x_center):
            if not columns:
                row_cells = [[token]]
                break
            token_center = _token_x_center(token)
            closest_index = min(range(len(columns)), key=lambda idx: abs(token_center - float(columns[idx]["x_center"])))
            row_cells[closest_index].append(token)
        table_cells.append([
            {
                "column_index": column["column_index"],
                "tokens": cell_tokens,
                "text": " ".join(t.get("text", "") for t in sorted(cell_tokens, key=lambda t: t["x0"])).strip(),
                "bbox": bbox_for_tokens(cell_tokens),
            }
            for column, cell_tokens in zip(columns, row_cells)
        ])
    return table_cells


def _infer_table_category_from_grid(table_cells: List[List[Dict[str, Any]]], columns: List[Dict[str, Any]]) -> Optional[str]:
    if not table_cells:
        return None

    header_text = " ".join(cell.get("text", "").lower() for cell in table_cells[0] if cell.get("text"))
    if any(label in header_text for label in ("drug", "dose", "days", "instruction", "medicine", "frequency", "qunt", "qty")):
        return "medication"
    if any(label in header_text for label in ("test", "result", "unit", "range", "normal", "investigation", "lab")):
        return "lab"
    if any(label in header_text for label in ("parameter", "value", "reading", "pulse", "bp", "temperature", "temp", "spo2")):
        return "vitals"
    if any(label in header_text for label in ("diagnosis", "icd", "procedure", "observation", "finding")):
        return "diagnosis"

    if len(columns) >= 2 and len(table_cells) >= 2:
        numeric_last_column = 0
        data_rows = 0
        for row_cells in table_cells[1:]:
            non_empty = [cell.get("text", "").strip() for cell in row_cells if cell.get("text", "").strip()]
            if not non_empty:
                continue
            data_rows += 1
            last_text = non_empty[-1].replace(",", "").replace("Rs.", "").replace("INR", "").strip()
            try:
                float(last_text)
                numeric_last_column += 1
            except ValueError:
                pass
        if data_rows and numeric_last_column >= max(1, data_rows // 2):
            return "expense"

    if len(columns) >= 4:
        return "medication"

    return None


def detect_generic_table_regions(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect ALL types of structured tables using generic grid/row detection.
    
    Heuristics:
    1. Group tokens into rows by Y coordinate
    2. Find consecutive rows with 2+ columns
    3. Classify by content keywords
    """
    if not tokens:
        return []
    
    detected_tables: List[Dict[str, Any]] = []
    rows = cluster_rows_by_y(tokens)
    
    if len(rows) < 2:
        return []
    
    # Scan for table regions (consecutive rows with similar structure)
    i = 0
    while i < len(rows):
        current_row = rows[i]
        
        # Need at least 2 columns in a row to be table-like
        if len(current_row) < 2:
            i += 1
            continue
        
        # Collect consecutive rows with similar X-alignment
        table_candidate_rows = [current_row]
        j = i + 1
        
        current_x_positions = sorted(set(t["x0"] for t in current_row))
        
        # Look ahead for rows with similar X structure
        while j < len(rows):
            next_row = rows[j]
            
            # Skip rows that are too short
            if len(next_row) < 2:
                j += 1
                continue
            
            next_x_positions = sorted(set(t["x0"] for t in next_row))
            
            # Check if X-alignment is similar
            if len(next_x_positions) >= len(current_x_positions) * 0.6:
                table_candidate_rows.append(next_row)
                j += 1
            else:
                break
        
        # If we found 2+ consecutive rows, analyze as potential table
        if len(table_candidate_rows) >= 2:
            table_tokens = [token for row in table_candidate_rows for token in row]
            columns = _cluster_columns_by_x(table_tokens)
            table_cells = _build_table_cells(table_candidate_rows, columns)
            inferred_category = _infer_table_category_from_grid(table_cells, columns)

            # Classify the table using grid/column inference first, then fallback on heuristic content.
            table_category = inferred_category or classify_table_category(
                " ".join(t.get("text", "") for row in table_candidate_rows for t in sorted(row, key=lambda t: t["x0"]))
            )
            confidence = min(0.95, 0.60 + (len(table_candidate_rows) * 0.05) + (len(columns) * 0.05))
            detected_tables.append({
                "type": "generic_table",
                "table_category": table_category,
                "confidence": confidence,
                "bbox": bbox_for_tokens(table_tokens),
                "tokens": table_tokens,
                "cells": table_cells,
                "rows": [
                    {
                        "tokens": row,
                        "bbox": bbox_for_tokens(row),
                        "cells": table_cells[idx],
                        "y_center": sum(t["y0"] + t["y1"] for t in row) / (2 * len(row)),
                        "row_index": idx,
                    }
                    for idx, row in enumerate(table_candidate_rows)
                ],
                "columns": columns,
                "row_count": len(table_candidate_rows),
            })
            logger.info(
                f"[LIGHTWEIGHT_LAYOUT] Detected {table_category or 'generic'} table: {len(table_candidate_rows)} rows, {len(columns)} columns"
            )
        
        i = max(i + 1, j)
    
    return detected_tables


def find_table_region(tokens: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Backward compatibility wrapper."""
    tables = detect_generic_table_regions(tokens)
    for t in tables:
        if t.get("table_category") == "expense":
            return t
    return None


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
        
        # 5. Detect generic tables (all types: expense, medication, lab, vitals, diagnosis)
        detected_tables = detect_generic_table_regions(page_tokens)
        for table in detected_tables:
            table["page"] = page_no
            result["sections"].append(table)
            logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected {table.get('table_category')} table on page {page_no}")
    
    logger.info(f"[LIGHTWEIGHT_LAYOUT] Detected {len(result['sections'])} sections total (coordinate-native)")
    return result
