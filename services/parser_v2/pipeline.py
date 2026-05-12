import json
import logging
from typing import List, Dict, Any
from .models import Token, DocumentStructure

logger = logging.getLogger("parser-debug")
from .layout_detector import detect_regions
from .table_reconstructor import reconstruct_table
from .form_extractor import extract_fields
from .schema_normalizer import normalize_fields, normalize_tables
from .debug_overlay import generate_overlays
from .document_processor import DocumentProcessor
from PIL import Image
from typing import Optional


def parse_document(ocr_tokens_json: List[Dict[str, Any]], page_images: Optional[Dict[int, Image]] = None, debug_dir: str = "debug") -> DocumentStructure:

    """
    Main entrypoint for parser_v2 Phase 1.
    Expects input list of dicts: {"text": str, "x0": float, "y0": float, "x1": float, "y1": float, "page": int}
    """
    # 1. Parse tokens
    logger.info("[PARSER_V2 ACTIVE]")
    tokens = [Token(**t) for t in ocr_tokens_json]
    
    # 2. Detect Regions (Model-Assisted or Heuristic Fallback)
    doc = None
    if page_images:
        doc = DocumentProcessor.process(ocr_tokens_json, page_images=page_images, debug_dir=debug_dir)
    
    if not doc:
        logger.info("[PIPELINE] Falling back to geometric heuristics for layout detection")
        regions = detect_regions(tokens)
        
        # 3. Reconstruct Tables and Extract Forms (Heuristic path)
        tables = []
        fields = []
        for region in regions:
            if region.region_type == "expense_table":
                table_region = reconstruct_table(region)
                tables.append(table_region)
            elif region.region_type in ["patient_form", "hospitalization_form"]:
                extracted_fields = extract_fields(region)
                fields.extend(extracted_fields)
        
        doc = DocumentStructure(
            regions=regions,
            tables=tables,
            fields=fields
        )
    else:
        logger.info(f"[PIPELINE] Model-assisted detection found {len(doc.regions)} regions and {len(doc.tables)} tables")
        # For model-detected regions that are forms, we still need to run our form extractor
        # because PP-Structure doesn't do our semantic key-value mapping
        all_fields = []
        for region in doc.regions:
            if region.region_type in ["form", "patient_form", "hospitalization_form", "text"]:
                extracted_fields = extract_fields(region)
                all_fields.extend(extracted_fields)
        doc.fields = all_fields
            
    # 4. Normalize Data (Phase 2B/C)
    doc.normalized_fields = normalize_fields(doc.fields)
    doc.normalized_expenses = normalize_tables(doc.tables)
    
    # 5. Generate Visual Debug Overlays
    if debug_dir:
        generate_overlays(doc, output_dir=debug_dir, 
                         normalized_fields=doc.normalized_fields, 
                         normalized_expenses=doc.normalized_expenses)
        
    return doc



def process_file(json_path: str, debug_dir: str = "debug") -> DocumentStructure:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if isinstance(data, dict) and "ocr_pages" in data:
        tokens = []
        for page in data["ocr_pages"]:
            for t in page.get("tokens", []):
                t["page"] = page.get("page_number", 1)
                tokens.append(t)
        return parse_document(tokens, debug_dir=debug_dir)
    elif isinstance(data, list):
        return parse_document(data, debug_dir=debug_dir)
    else:
        raise ValueError("Invalid JSON structure")
