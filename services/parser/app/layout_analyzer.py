"""Document layout analyzer — PP-StructureV3 based.

This module exposes `analyze_layout(ocr_tokens, page_images=None)` which
returns structured layout including sections, tables, and key-value regions
using **PP-StructureV3 as the mandatory primary engine**.

ARCHITECTURE:
- PP-StructureV3 is REQUIRED for production document understanding.
- Heuristics are ONLY available as emergency fallback (not recommended).
- FAIL FAST if PP-Structure is unavailable.

Input tokens (canonical):
{
    "text": str,
    "x0": float,
    "y0": float,
    "x1": float,
    "y1": float,
    "page": int
}

Output from PP-StructureV3:
{
  "sections": [
    {
      "type": "table",  # or "key_value", "text", "title", etc.
      "bbox": [x0, y0, x1, y1],
      "cells": [...],  # For tables only
      "tokens": [...]
    }
  ]
}

Debug artifacts written:
- pp_structure_raw.json: Raw PP-StructureV3 output
- detected_tables.json: Parsed table regions with cells
- detected_key_value_blocks.json: Parsed KV pairs (patient info, insurance, etc.)
- layout_regions_visualized.json: Bounding boxes for visualization
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


# ================================================================
# FALLBACK HELPERS ONLY
# ================================================================
# These functions are kept for emergency fallback only (not primary)
# and are not used in the normal PP-StructureV3 path.

# ================================================================
# PP-StructureV3 Initialization (Mandatory)
# ================================================================
_PP_STRUCTURE_LOADED = False
_PP_STRUCTURE_ERROR: Optional[str] = None
_PP_STRUCTURE_ENGINE: Optional[Any] = None


def _load_pp_structure() -> bool:
    """Load PP-StructureV3 on-demand. Fail explicitly if unavailable."""
    global _PP_STRUCTURE_LOADED, _PP_STRUCTURE_ERROR, _PP_STRUCTURE_ENGINE
    if _PP_STRUCTURE_LOADED:
        return _PP_STRUCTURE_ENGINE is not None
    _PP_STRUCTURE_LOADED = True
    try:
        from paddleocr import PPStructureV3
        logger.info("OK: PP-StructureV3 library available")
        try:
            # PPStructureV3 downloads models on first initialization (may take time)
            _PP_STRUCTURE_ENGINE = PPStructureV3(use_table_recognition=True)
            logger.info("OK: PP-StructureV3 engine initialized successfully")
            return True
        except Exception as e:
            _PP_STRUCTURE_ERROR = f"PP-StructureV3 initialization failed: {e}"
            logger.error(_PP_STRUCTURE_ERROR)
            return False
    except ImportError as e:
        _PP_STRUCTURE_ERROR = f"PP-StructureV3 not installed: {e}. Install: pip install paddleocr[doc-parser]>=3.0.0"
        logger.error(_PP_STRUCTURE_ERROR)
        return False
    except Exception as e:
        _PP_STRUCTURE_ERROR = f"Unexpected error loading PP-StructureV3: {e}"
        logger.error(_PP_STRUCTURE_ERROR)
        return False


def bbox_for_tokens(tokens: List[Dict[str, Any]]) -> List[float]:
    if not tokens:
        return [0, 0, 0, 0]
    x0 = min(t["x0"] for t in tokens)
    y0 = min(t["y0"] for t in tokens)
    x1 = max(t["x1"] for t in tokens)
    y1 = max(t["y1"] for t in tokens)
    return [x0, y0, x1, y1]


def token_center(t: Dict[str, Any]) -> Tuple[float, float]:
    return ((t["x0"] + t["x1"]) / 2.0, (t["y0"] + t["y1"]) / 2.0)


def group_by_page(tokens: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    pages = defaultdict(list)
    for t in tokens:
        pages[int(t.get("page", 0))].append(t)
    return pages


def cluster_rows(tokens: List[Dict[str, Any]], y_tol: float = 6.0) -> List[List[Dict[str, Any]]]:
    # cluster tokens into rows by their vertical center
    if not tokens:
        return []
    toks = sorted(tokens, key=lambda t: token_center(t)[1])
    rows: List[List[Dict[str, Any]]] = []
    for t in toks:
        cy = token_center(t)[1]
        if not rows:
            rows.append([t])
            continue
        last_row = rows[-1]
        last_cy = sum(token_center(x)[1] for x in last_row) / len(last_row)
        if abs(cy - last_cy) <= y_tol:
            last_row.append(t)
        else:
            rows.append([t])
    return rows


def detect_tables_by_grid(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Heuristic: find clusters with multiple rows and repeated column x positions
    tables: List[Dict[str, Any]] = []
    rows = cluster_rows(tokens)
    if len(rows) < 2:
        return tables
    # compute candidate columns by analyzing x-centers across rows
    cols_x = []
    for r in rows:
        xs = sorted(token_center(t)[0] for t in r)
        cols_x.extend(xs)
    if not cols_x:
        return tables
    # cluster x positions into columns
    cols_x_sorted = sorted(cols_x)
    col_coords: List[float] = []
    cur_cluster = [cols_x_sorted[0]]
    for x in cols_x_sorted[1:]:
        if abs(x - cur_cluster[-1]) <= 12:  # tolerance
            cur_cluster.append(x)
        else:
            col_coords.append(sum(cur_cluster) / len(cur_cluster))
            cur_cluster = [x]
    if cur_cluster:
        col_coords.append(sum(cur_cluster) / len(cur_cluster))

    # require at least 2 columns for a table
    if len(col_coords) < 2:
        return tables

    # build table rows mapped to columns
    table_rows: List[List[Dict[str, Any]]] = []
    for r in rows:
        row_cells = [None] * len(col_coords)
        for t in r:
            cx = token_center(t)[0]
            # find closest column
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

    # compute table bbox
    flat = [t for row in table_rows for cell in row if cell for t in cell]
    bbox = bbox_for_tokens(flat)

    # format cells as simple serializable cells
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


def label_section_by_heading(tokens: List[Dict[str, Any]]) -> Optional[str]:
    # Look for heading keywords in tokens (simple heuristic)
    heading_text = " ".join(t["text"] for t in tokens).lower()
    if re.search(r"patient|patient name|date of birth|dob", heading_text):
        return "patient_info"
    if re.search(r"insurance|insured|policy|subscriber|payer", heading_text):
        return "insurance_info"
    if re.search(r"hospital|admission|discharge|hospitalization", heading_text):
        return "hospitalization"
    if re.search(r"expense|charge|item|amount|claim|total", heading_text):
        # ambiguous; prefer table detection for expense_table
        return None
    if re.search(r"summary|total claim|totals", heading_text):
        return "summary"
    if re.search(r"declaration|signature|footer|terms", heading_text):
        return "declaration_footer"
    return None


def analyze_layout(ocr_tokens: List[Dict[str, Any]], page_images: Optional[Dict[int, Any]] = None, debug_dump_dir: Optional[str] = None) -> Dict[str, Any]:
    """Analyze document layout using PP-StructureV3 as mandatory primary engine.
    
    Parameters
    ----------
    ocr_tokens : list of dicts
        Canonical OCR tokens with real geometry (x0, y0, x1, y1, page, text)
    page_images : dict[int, Image], optional
        PIL Images mapped by page number (required for PP-StructureV3)
    debug_dump_dir : str, optional
        Directory to write debug artifacts (pp_structure_raw.json, etc.)
    
    Returns
    -------
    dict with "sections" key containing layout regions detected by PP-StructureV3
    
    Raises
    ------
    RuntimeError
        If PP-StructureV3 is unavailable or initialization fails (FAIL FAST policy)
    """
    # Validate input
    if not ocr_tokens:
        raise ValueError("analyze_layout requires token-level OCR with geometry; received empty token list")
    for t in ocr_tokens[:10]:
        if not all(k in t for k in ("x0", "y0", "x1", "y1")):
            raise ValueError("analyze_layout requires tokens with x0,y0,x1,y1 coordinates")

    # MANDATORY: Load PP-StructureV3
    if not _load_pp_structure():
        raise RuntimeError(
            f"PP-StructureV3 is required for production parsing. "
            f"Error: {_PP_STRUCTURE_ERROR}. "
            f"Install: pip install paddleocr[doc-parser]>=3.0.0"
        )
    
    if _PP_STRUCTURE_ENGINE is None:
        raise RuntimeError("PP-StructureV3 engine failed to initialize. Cannot proceed.")
    
    # Group tokens by page
    pages = defaultdict(list)
    for t in ocr_tokens:
        pages[int(t.get("page", 1))].append(t)

    result: Dict[str, Any] = {"sections": []}
    pp_structure_raw_output = {}
    debug_artifacts = {
        "tables": [],
        "key_value_blocks": [],
        "regions": [],
    }

    # Run PP-StructureV3 on each page
    for page_no, toks in sorted(pages.items()):
        if not toks or page_no not in (page_images or {}):
            logger.warning(f"Page {page_no} has tokens but no image provided to PP-StructureV3 — skipping layout analysis for this page")
            continue
        
        try:
            img = page_images[page_no]
            # Convert PIL Image to numpy array if needed (PP-StructureV3 requires numpy or str path)
            import numpy as np
            if hasattr(img, 'tobytes'):  # PIL Image
                img_array = np.array(img)
            else:
                img_array = img
            
            logger.info(f"Running PP-StructureV3 on page {page_no}")
            pp_output = _PP_STRUCTURE_ENGINE.predict(img_array)  # Call predict() with numpy array
            pp_structure_raw_output[f"page_{page_no}"] = pp_output
            
            # Parse PP-StructureV3 output into sections
            sections = _parse_pp_structure_output(pp_output, page_no, toks, debug_artifacts)
            result["sections"].extend(sections)
            logger.info(f"OK: Page {page_no} detected {len(sections)} layout sections")
        except Exception as e:
            logger.exception(f"PP-StructureV3 failed on page {page_no}")
            raise RuntimeError(f"PP-StructureV3 inference failed on page {page_no}: {e}") from e

    # Write debug artifacts if requested
    if debug_dump_dir:
        _write_layout_debug_artifacts(debug_dump_dir, pp_structure_raw_output, debug_artifacts)

    return result


def _parse_pp_structure_output(pp_output: Any, page_no: int, page_tokens: List[Dict[str, Any]], debug_artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse PP-StructureV3 output into canonical section format.
    
    PP-StructureV3 returns a list of layout elements, each with:
    - bbox: [x0, y0, x1, y1]
    - type: "table" | "key_value" | "text" | "title" | "footer"
    - tokens/content: recognized text/structure
    
    Convert to our canonical format:
    {
        "type": "table" | "key_value" | "text" | "title" | "footer",
        "bbox": [x0, y0, x1, y1],
        "tokens": [...],  # tokens within this region
        "cells": [...],  # For tables: cell grid
        "page": page_no
    }
    """
    sections: List[Dict[str, Any]] = []
    if not pp_output:
        return sections

    # PP-StructureV3 returns a dict or list; normalize
    if isinstance(pp_output, dict):
        pp_output = pp_output.get("blocks", []) or pp_output.get("elements", []) or []
    if not isinstance(pp_output, list):
        pp_output = [pp_output]

    for element in pp_output:
        if not isinstance(element, dict):
            continue
        
        bbox = element.get("bbox") or element.get("box")
        if not bbox or len(bbox) < 4:
            continue
        
        elem_type = element.get("type", "text").lower()
        
        # Map PP-Structure types to our canonical types
        canonical_type = {
            "table": "table",
            "key_value": "key_value",
            "kv": "key_value",
            "title": "title",
            "header": "title",
            "footer": "footer",
            "text": "text",
            "paragraph": "text",
        }.get(elem_type, "text")

        # Extract tokens within bbox from page_tokens
        region_tokens = [
            t for t in page_tokens
            if bbox[0] <= t.get("x0", 0) and t.get("x1", 999999) <= bbox[2]
               and bbox[1] <= t.get("y0", 0) and t.get("y1", 999999) <= bbox[3]
        ]

        section: Dict[str, Any] = {
            "type": canonical_type,
            "bbox": bbox,
            "tokens": region_tokens,
            "page": page_no,
        }

        # For tables: extract cell structure if available
        if canonical_type == "table":
            cell_grid = element.get("cells") or []
            section["cells"] = cell_grid or _reconstruct_table_cells_from_tokens(region_tokens)
            debug_artifacts["tables"].append(section)

        # For key_value: extract KV pairs
        elif canonical_type == "key_value":
            kv_pairs = element.get("kv_pairs") or element.get("key_value_pairs") or []
            section["key_value_pairs"] = kv_pairs
            debug_artifacts["key_value_blocks"].append(section)

        # For other types: just track as regions
        else:
            debug_artifacts["regions"].append(section)

        sections.append(section)

    return sections


def _reconstruct_table_cells_from_tokens(tokens: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Fallback: reconstruct table cells from tokens when PP-Structure doesn't provide them."""
    if not tokens:
        return []
    
    # Group tokens into rows by Y coordinate
    rows = cluster_rows(tokens, y_tol=6.0)
    cells_grid: List[List[Dict[str, Any]]] = []
    for row in rows:
        # Sort by X coordinate to get column order
        sorted_row = sorted(row, key=lambda t: t["x0"])
        row_cells = [
            {"text": t["text"], "tokens": [t], "bbox": [t["x0"], t["y0"], t["x1"], t["y1"]]}
            for t in sorted_row
        ]
        cells_grid.append(row_cells)
    return cells_grid


def _write_layout_debug_artifacts(dump_dir: str, pp_structure_raw: Dict[str, Any], artifacts: Dict[str, Any]) -> None:
    """Write debug artifacts for layout analysis inspection."""
    import json
    dump_path = Path(dump_dir)
    dump_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Raw PP-StructureV3 output
        (dump_path / "pp_structure_raw.json").write_text(
            json.dumps(pp_structure_raw, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"OK: Wrote pp_structure_raw.json")
    except Exception as e:
        logger.warning(f"Failed to write pp_structure_raw.json: {e}")
    
    try:
        # 2. Detected tables
        (dump_path / "detected_tables.json").write_text(
            json.dumps(artifacts.get("tables", []), indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"OK: Wrote detected_tables.json ({len(artifacts.get('tables', []))} tables)")
    except Exception as e:
        logger.warning(f"Failed to write detected_tables.json: {e}")
    
    try:
        # 3. Detected key-value blocks
        (dump_path / "detected_key_value_blocks.json").write_text(
            json.dumps(artifacts.get("key_value_blocks", []), indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"OK: Wrote detected_key_value_blocks.json ({len(artifacts.get('key_value_blocks', []))} KV blocks)")
    except Exception as e:
        logger.warning(f"Failed to write detected_key_value_blocks.json: {e}")
    
    try:
        # 4. All regions (for visualization)
        all_regions = (
            artifacts.get("tables", []) +
            artifacts.get("key_value_blocks", []) +
            artifacts.get("regions", [])
        )
        (dump_path / "layout_regions_visualized.json").write_text(
            json.dumps(
                {
                    "regions": [
                        {
                            "type": r.get("type"),
                            "bbox": r.get("bbox"),
                            "page": r.get("page"),
                            "token_count": len(r.get("tokens", [])),
                        }
                        for r in all_regions
                    ],
                    "total_regions": len(all_regions),
                },
                indent=2,
            ),
            encoding="utf-8"
        )
        logger.info(f"OK: Wrote layout_regions_visualized.json ({len(all_regions)} regions)")
    except Exception as e:
        logger.warning(f"Failed to write layout_regions_visualized.json: {e}")


def _heuristic_page_sections(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    if not tokens:
        return sections
    rows = cluster_rows(tokens)
    for r in rows[:6]:
        typ = label_section_by_heading(r)
        if typ:
            bbox = bbox_for_tokens(r)
            sections.append({"type": typ, "bbox": bbox, "tokens": r})
    tables = detect_tables_by_grid(tokens)
    for t in tables:
        sections.append({"type": "expense_table", "bbox": t["bbox"], "cells": t["cells"]})
    if not sections:
        sections.append({"type": "visual_block", "bbox": bbox_for_tokens(tokens), "tokens": tokens})
    return sections


__all__ = ["analyze_layout"]
