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
        logger.info("PP-DocLayoutV3 engine already initialised")
        return True
    try:
        from paddlex import create_model
        logger.info("Initializing PP-DocLayoutV3 engine...")
        # Use the local DocLayout model found in .paddlex cache
        _PP_STRUCTURE_ENGINE = create_model("PP-DocLayoutV3")
        logger.info("PP-DocLayoutV3 engine initialised successfully")
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


def _normalize_bbox(bbox: List[float], page_width: float | None, page_height: float | None) -> List[float]:
    if not bbox or len(bbox) != 4:
        return [0.0, 0.0, 0.0, 0.0]

    x0, y0, x1, y1 = [float(value) for value in bbox]
    max_value = max(abs(x0), abs(y0), abs(x1), abs(y1))

    if page_width and page_height and max_value <= 1.5:
        return [x0 * page_width, y0 * page_height, x1 * page_width, y1 * page_height]

    return [x0, y0, x1, y1]


def _bbox_overlap(token_bbox: List[float], region_bbox: List[float], padding: float = 6.0) -> bool:
    if not token_bbox or not region_bbox:
        return False

    tx0, ty0, tx1, ty1 = token_bbox
    rx0, ry0, rx1, ry1 = region_bbox
    rx0 -= padding
    ry0 -= padding
    rx1 += padding
    ry1 += padding

    horizontal_overlap = tx0 <= rx1 and tx1 >= rx0
    vertical_overlap = ty0 <= ry1 and ty1 >= ry0
    return horizontal_overlap and vertical_overlap

def _parse_pp_structure_output(
    pp_output: Any,
    page_no: int,
    page_tokens: List[Dict[str, Any]],
    page_size: tuple[int, int] | None = None,
) -> List[Dict[str, Any]]:
    """Parses raw AI engine output into canonical section format."""
    logger.warning(f"[LAYOUT_DEBUG] _parse_pp_structure_output called for page {page_no}, pp_output type: {type(pp_output)}")
    sections = []
    
    # Handle both direct list output and wrapped Result objects
    items = pp_output
    logger.warning(f"[LAYOUT_DEBUG] Raw pp_output type: {type(pp_output)}, name: {type(pp_output).__name__}")
    if hasattr(pp_output, "doc_parsing_results"):
        items = pp_output.doc_parsing_results
    elif isinstance(pp_output, dict):
        if "doc_parsing_results" in pp_output:
            items = pp_output["doc_parsing_results"]
        elif "layout" in pp_output:
            items = pp_output["layout"]
        elif "predictions" in pp_output:
            items = pp_output["predictions"]
        elif "results" in pp_output:
            items = pp_output["results"]
        elif "boxes" in pp_output and "type" in pp_output:
            items = [pp_output]
    elif hasattr(pp_output, "to_dict"):
        try:
            output_dict = pp_output.to_dict()
            if isinstance(output_dict, dict) and "layout" in output_dict:
                items = output_dict["layout"]
            elif isinstance(output_dict, dict) and "predictions" in output_dict:
                items = output_dict["predictions"]
            elif isinstance(output_dict, dict) and "results" in output_dict:
                items = output_dict["results"]
        except Exception:
            pass
    # Handle LayoutAnalysisResult specifically
    elif "LayoutAnalysisResult" in str(type(pp_output)):
        try:
            logger.info(f"[LAYOUT_DEBUG] LayoutAnalysisResult type: {type(pp_output)}")
            logger.info(f"[LAYOUT_DEBUG] LayoutAnalysisResult attributes: {[attr for attr in dir(pp_output) if not attr.startswith('_')]}")
            # Try to access the result data directly
            if hasattr(pp_output, "layout"):
                items = pp_output.layout
                logger.info(f"[LAYOUT_DEBUG] Found layout attribute with {len(items) if isinstance(items, list) else 'non-list'} items")
            elif hasattr(pp_output, "predictions"):
                items = pp_output.predictions
                logger.info(f"[LAYOUT_DEBUG] Found predictions attribute with {len(items) if isinstance(items, list) else 'non-list'} items")
            elif hasattr(pp_output, "results"):
                items = pp_output.results
                logger.info(f"[LAYOUT_DEBUG] Found results attribute with {len(items) if isinstance(items, list) else 'non-list'} items")
            else:
                # Try converting to dict and look for layout data
                output_dict = pp_output.to_dict() if hasattr(pp_output, "to_dict") else {}
                logger.info(f"[LAYOUT_DEBUG] to_dict() result keys: {list(output_dict.keys()) if isinstance(output_dict, dict) else 'not dict'}")
                if isinstance(output_dict, dict):
                    items = output_dict.get("layout") or output_dict.get("predictions") or output_dict.get("results") or []
                    logger.info(f"[LAYOUT_DEBUG] Extracted items from dict: {len(items) if isinstance(items, list) else 'non-list'} items")
        except Exception as e:
            logger.warning(f"Failed to parse LayoutAnalysisResult for page {page_no}: {e}")
            return sections
    
    # If items is a single non-list object, try to coerce it into a list/dict
    if not isinstance(items, list):
        single = items
        coerced_single = None
        # If it's already a dict-like with bbox/type, wrap it
        if isinstance(single, dict) and "type" in single and "bbox" in single:
            items = [single]
        else:
            # Try converting the single object to a dict
            try:
                if hasattr(single, "to_dict"):
                    od = single.to_dict()
                    if isinstance(od, dict) and ("layout" in od or "predictions" in od or "results" in od):
                        # prefer inner list
                        inner = od.get("layout") or od.get("predictions") or od.get("results")
                        if isinstance(inner, list):
                            items = inner
                        else:
                            # If inner is a dict representing a single item
                            items = [inner] if isinstance(inner, dict) else []
                    elif isinstance(od, dict) and "type" in od and "bbox" in od:
                        items = [od]
                    else:
                        coerced_single = od
            except Exception:
                coerced_single = None

            if not isinstance(items, list):
                # Fallback: extract common attributes from object
                try:
                    itype = getattr(single, "type", None) or getattr(single, "label", None) or getattr(single, "category", None)
                    bb = getattr(single, "bbox", None) or getattr(single, "box", None) or getattr(single, "boxes", None)
                    score = getattr(single, "score", None) or getattr(single, "confidence", None)
                    candidate: Dict[str, Any] = {"type": itype or "text", "bbox": bb or []}
                    if score is not None:
                        candidate["score"] = score
                    items = [candidate]
                except Exception:
                    # Last resort: if we obtained a dict-like from to_dict, use it
                    if isinstance(coerced_single, dict) and ("type" in coerced_single and "bbox" in coerced_single):
                        items = [coerced_single]
                    else:
                        logger.warning(f"Unexpected AI output format for page {page_no}: {type(pp_output).__name__}")
                        return sections

    # Coerce non-dict items (e.g., PaddleX result objects) into plain dicts
    coerced_items: List[dict] = []
    for item in items:
        if isinstance(item, dict):
            coerced_items.append(item)
            continue
        # Try common conversion methods for model result objects
        try:
            if hasattr(item, "to_dict"):
                od = item.to_dict()
                if isinstance(od, dict):
                    coerced_items.append(od)
                    continue
        except Exception:
            pass

        # Fallback: extract common attributes
        try:
            itype = getattr(item, "type", None) or getattr(item, "label", None) or getattr(item, "category", "text")
            bb = getattr(item, "bbox", None) or getattr(item, "box", None) or getattr(item, "boxes", None)
            score = getattr(item, "score", None) or getattr(item, "confidence", None)
            candidate: Dict[str, Any] = {"type": itype, "bbox": bb}
            if score is not None:
                candidate["score"] = score
            # Some PaddleX objects expose a nested 'layout' or 'results' list
            if hasattr(item, "layout") and not bb:
                candidate = {"type": "group", "bbox": getattr(item, "layout", [])}
            coerced_items.append(candidate)
        except Exception:
            logger.debug(f"Skipping unsupported layout item type on page {page_no}: {type(item).__name__}")
            continue

    items = coerced_items

    for item in items:
        # PaddleX Result objects often have a 'boxes' or 'layout' attribute
        # but the current PP-DocLayoutV3 often returns a list of dicts with 'type' and 'bbox'
        if not isinstance(item, dict):
            logger.debug(f"Skipping unsupported layout item type on page {page_no}: {type(item).__name__}")
            continue
        stype = item.get("type", "text").lower()
        bbox = _normalize_bbox(item.get("bbox", [0, 0, 0, 0]), *(page_size or (None, None)))
        
        # Collect tokens that overlap the detected bbox. Some layout models emit
        # slightly loose boxes, and a strict inside check can drop real rows.
        section_tokens = [
            t for t in page_tokens 
            if _bbox_overlap([t["x0"], t["y0"], t["x1"], t["y1"]], bbox)
        ]

        if not section_tokens:
            section_tokens = [
                t for t in page_tokens
                if t.get("text") and _bbox_overlap([t["x0"], t["y0"], t["x1"], t["y1"]], bbox, padding=18.0)
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
        logger.warning("PP-DocLayoutV3 unavailable; falling back to geometry-only parsing: %s", _PP_STRUCTURE_ERROR)
        return {"sections": [], "error": _PP_STRUCTURE_ERROR, "layout_engine": "geometry_fallback"}

    result = {"sections": [], "layout_engine": "PP-DocLayoutV3"}
    pages = defaultdict(list)
    for t in ocr_tokens:
        pages[int(t.get("page", 1))].append(t)

    logger.info(
        "Layout analysis started with PP-DocLayoutV3 for %d page(s); has_page_images=%s has_document_paths=%s",
        len(pages),
        bool(page_images),
        bool(document_paths),
    )

    for page_no, toks in pages.items():
        img_array = None
        page_size = None
        if page_images and page_no in page_images:
            img = page_images[page_no]
            if hasattr(img, 'convert'):
                img = img.convert("RGB")
            img_array = np.array(img)
            page_size = (img.width, img.height)
        
        if img_array is None:
            logger.warning(
                "PP-DocLayoutV3 cannot run on page %s because no page image was available; geometry-only parsing will cover this page.",
                page_no,
            )
            continue

        try:
            # Predict layout regions
            predictions = _PP_STRUCTURE_ENGINE.predict(img_array)
            # Result is a generator in some paddlex versions
            results_list = list(predictions)
            if not results_list:
                logger.warning("PP-DocLayoutV3 returned no predictions for page %s", page_no)
                continue
            
            # The first item in the list is the result for the single image provided
            pp_output = results_list[0]
            sections = _parse_pp_structure_output(pp_output, page_no, toks, page_size=page_size)
            logger.info("PP-DocLayoutV3 produced %d section(s) on page %s", len(sections), page_no)
            result["sections"].extend(sections)
            
        except Exception as e:
            logger.error("PP-DocLayoutV3 failed on page %s: %s", page_no, e)
            continue

    return result
