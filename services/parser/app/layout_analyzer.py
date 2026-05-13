import logging
import os
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import UTC, datetime
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

# ================================================================
# PP-StructureV3 Initialization
# ================================================================
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_allocator_strategy"] = "naive_best_fit"

_PP_STRUCTURE_ENGINE = None
_PP_STRUCTURE_ERROR = None

def init_pp_structure():
    global _PP_STRUCTURE_ENGINE, _PP_STRUCTURE_ERROR
    if _PP_STRUCTURE_ENGINE is not None:
        return True
    try:
        from paddlex import create_model
        logger.info("Initializing PP-DocLayoutV3 engine...")
        # Use the local DocLayout model found in .paddlex cache
        _PP_STRUCTURE_ENGINE = create_model("PP-DocLayoutV3")
        return True
    except Exception as e:
        _PP_STRUCTURE_ERROR = f"Failed to initialize AI Engine: {e}"
        logger.error(_PP_STRUCTURE_ERROR)
        return False

def bbox_for_tokens(tokens: List[Dict[str, Any]]) -> List[float]:
    """Computes a bounding box [x0, y0, x1, y1] for a list of tokens."""
    if not tokens:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        float(min(t.get("x0", 0.0) for t in tokens)),
        float(min(t.get("y0", 0.0) for t in tokens)),
        float(max(t.get("x1", 0.0) for t in tokens)),
        float(max(t.get("y1", 0.0) for t in tokens))
    ]

def token_center(t: Dict[str, Any]) -> Tuple[float, float]:
    """Returns the (x, y) center of a token."""
    return ((t["x0"] + t["x1"]) / 2.0, (t["y0"] + t["y1"]) / 2.0)

def cluster_rows(tokens: List[Dict[str, Any]], y_tol: float = 6.0) -> List[List[Dict[str, Any]]]:
    """Clusters tokens into rows based on Y-coordinate overlap."""
    if not tokens:
        return []
    toks = sorted(tokens, key=lambda t: token_center(t)[1])
    rows: List[List[Dict[str, Any]]] = []
    for t in toks:
        if not rows:
            rows.append([t])
            continue
        prev_y = sum(token_center(rt)[1] for rt in rows[-1]) / len(rows[-1])
        if abs(token_center(t)[1] - prev_y) <= y_tol:
            rows[-1].append(t)
        else:
            rows.append([t])
    return rows

def detect_tables_by_grid(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Heuristic table reconstruction using a geometric grid."""
    tables: List[Dict[str, Any]] = []
    rows = cluster_rows(tokens)
    if len(rows) < 2:
        return tables
    
    cols_x = []
    for r in rows:
        xs = sorted(token_center(t)[0] for t in r)
        cols_x.extend(xs)
    
    if not cols_x:
        return tables
        
    cols_x_sorted = sorted(cols_x)
    col_coords: List[float] = []
    cur_cluster = [cols_x_sorted[0]]
    for x in cols_x_sorted[1:]:
        if abs(x - cur_cluster[-1]) <= 12:
            cur_cluster.append(x)
        else:
            col_coords.append(sum(cur_cluster) / len(cur_cluster))
            cur_cluster = [x]
    if cur_cluster:
        col_coords.append(sum(cur_cluster) / len(cur_cluster))

    if len(col_coords) < 2:
        return tables

    table_rows: List[List[Dict[str, Any]]] = []
    for r in rows:
        row_cells = [None] * len(col_coords)
        for t in r:
            cx = token_center(t)[0]
            idx = min(range(len(col_coords)), key=lambda i: abs(col_coords[i] - cx))
            if row_cells[idx] is None:
                row_cells[idx] = [t]
            else:
                row_cells[idx].append(t)
        populated = sum(1 for c in row_cells if c)
        if populated >= 2:
            table_rows.append(row_cells)

    if not table_rows:
        return tables

    flat = [t for row in table_rows for cell in row if cell for t in cell]
    bbox = bbox_for_tokens(flat)
    cells = []
    for row in table_rows:
        row_texts = []
        for cell in row:
            if not cell:
                row_texts.append({"text": "", "tokens": []})
            else:
                texts = " ".join(t["text"] for t in sorted(cell, key=lambda x: x["x0"]))
                row_texts.append({"text": texts, "tokens": cell, "bbox": bbox_for_tokens(cell)})
        cells.append(row_texts)

    tables.append({"bbox": bbox, "cells": cells})
    return tables

def _parse_pp_structure_output(pp_output: Any, page_no: int, page_tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parses raw AI engine output into canonical section format."""
    sections = []
    
    # Handle both direct list output and wrapped Result objects
    items = pp_output
    if hasattr(pp_output, "doc_parsing_results"):
        items = pp_output.doc_parsing_results
    
    if not isinstance(items, list):
        logger.warning(f"Unexpected AI output format for page {page_no}")
        return sections

    for item in items:
        # PaddleX Result objects often have a 'boxes' or 'layout' attribute
        # but the current PP-DocLayoutV3 often returns a list of dicts with 'type' and 'bbox'
        stype = item.get("type", "text").lower()
        bbox = item.get("bbox", [0, 0, 0, 0])
        
        # Collect tokens inside this bbox
        section_tokens = [
            t for t in page_tokens 
            if t["x0"] >= bbox[0] - 5 and t["y0"] >= bbox[1] - 5
            and t["x1"] <= bbox[2] + 5 and t["y1"] <= bbox[3] + 5
        ]
        
        section = {
            "type": stype,
            "bbox": bbox,
            "page": page_no,
            "tokens": section_tokens
        }
        
        if stype == "table":
            # Use heuristic grid to reconstruct the table structure inside the detected area
            table_data = detect_tables_by_grid(section_tokens)
            if table_data:
                section["cells"] = table_data[0].get("cells", [])
        
        sections.append(section)
        
    return sections

def analyze_layout(ocr_tokens: List[Dict[str, Any]], page_images: Optional[Dict[int, Any]] = None, document_paths: Optional[List[str]] = None, debug_dump_dir: Optional[str] = None) -> Dict[str, Any]:
    """Primary layout analysis using PP-DocLayoutV3 with fallback mechanisms."""
    if not init_pp_structure():
        return {"sections": [], "error": _PP_STRUCTURE_ERROR}

    result = {"sections": []}
    pages = defaultdict(list)
    for t in ocr_tokens:
        pages[int(t.get("page", 1))].append(t)

    for page_no, toks in pages.items():
        img_array = None
        if page_images and page_no in page_images:
            img = page_images[page_no]
            if hasattr(img, 'convert'):
                img = img.convert("RGB")
            img_array = np.array(img)
        
        if img_array is None:
            logger.warning(f"No image available for page {page_no}, skipping AI layout.")
            continue

        try:
            # Predict layout regions
            predictions = _PP_STRUCTURE_ENGINE.predict(img_array)
            # Result is a generator in some paddlex versions
            results_list = list(predictions)
            if not results_list:
                continue
            
            # The first item in the list is the result for the single image provided
            pp_output = results_list[0]
            sections = _parse_pp_structure_output(pp_output, page_no, toks)
            result["sections"].extend(sections)
            
        except Exception as e:
            logger.error(f"AI Layout engine failed on page {page_no}: {e}")
            continue

    return result
