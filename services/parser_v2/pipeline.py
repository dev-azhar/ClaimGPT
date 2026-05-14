import json
import logging
from typing import List, Dict, Any
from .models import Token, DocumentStructure

logger = logging.getLogger("parser-debug")
from .layout_detector import detect_regions
from .table_reconstructor import reconstruct_table
from .form_extractor import extract_fields
from .schema_normalizer import normalize_fields, normalize_tables, normalize_table_fields, normalize_region_expenses
from .semantic_extractor import extract_semantics
from .debug_overlay import generate_overlays
from .document_processor import DocumentProcessor
from PIL import Image
from typing import Optional

from services.parser.app.form_extractor import extract_form_fields as extract_local_form_fields
from services.parser.app.lightweight_ner import extract_ner_entities as extract_local_entities
from services.parser.app.robust_field_extractor import RobustFieldExtractor


def parse_document(ocr_tokens_json: list[dict[str, Any]], page_images: Optional[dict[int, Image.Image]] = None, document_paths: Optional[list[str]] = None, debug_dir: str = "debug", claim_id: Optional[str] = None) -> DocumentStructure:


    """
    Main entrypoint for parser_v2 Phase 1 with document isolation support.
    
    Expects input list of dicts: 
    {"text": str, "x0": float, "y0": float, "x1": float, "y1": float, "page": int, 
     "document_id": str, "claim_id": str}
    
    Args:
        ocr_tokens_json: List of OCR token dictionaries with geometry and document metadata
        page_images: Optional dict mapping page numbers to PIL Image objects
        document_paths: Optional list of document file paths
        debug_dir: Directory to write debug artifacts
        claim_id: Optional claim ID to override tokens' claim_id values
    
    Returns:
        DocumentStructure with properly isolated regions by document
    """
    # 1. Parse tokens and inject claim_id if provided
    logger.info("[PARSER_V2 ACTIVE]")
    tokens = [Token(**t) for t in ocr_tokens_json]
    
    # Override claim_id if provided explicitly
    if claim_id:
        for token in tokens:
            if not token.claim_id:
                token.claim_id = claim_id
        logger.info(f"[DOCUMENT_ISOLATION] Set claim_id={claim_id} on tokens without claim_id")
    
    # Log token distribution across documents
    doc_pages = {}
    for token in tokens:
        key = (token.claim_id or "unknown", token.document_id or "unknown", token.page)
        doc_pages[key] = doc_pages.get(key, 0) + 1
    logger.info(f"[DOCUMENT_ISOLATION] Token distribution: {len(doc_pages)} unique (claim, document, page) combinations")
    
    # 2. Detect Regions (Model-Assisted or Heuristic Fallback)
    doc = None
    if page_images or document_paths:
        doc = DocumentProcessor.process(ocr_tokens_json, page_images=page_images, document_paths=document_paths, debug_dir=debug_dir)

    
    if not doc:
        logger.info("[PIPELINE] Falling back to geometric heuristics for layout detection")
        regions = detect_regions(tokens)
        
        # 3. Reconstruct Tables and Extract Forms (Heuristic path)
        tables = []
        fields = []
        for region in regions:
            if region.region_type in {"table", "expense_table"}:
                table_region = reconstruct_table(region)
                tables.append(table_region)
            elif region.region_type in ["patient_form", "hospitalization_form", "form"]:
                extracted_fields = extract_fields(region)
                fields.extend(extracted_fields)
        
        # RECURSIVE SCAN: If no tables were found on a page, try a tighter scan
        pages_with_tables = {t.page for t in tables}
        all_pages = {t.page for t in tokens}
        for pg in (all_pages - pages_with_tables):
            logger.info(f"[PIPELINE] No table on page {pg}. Running tighter recursive scan (12px)...")
            pg_tokens = [t for t in tokens if t.page == pg]
            h_regions = detect_regions(pg_tokens, gap_threshold=12.0)
            for h_reg in h_regions:
                if h_reg.region_type in {"table", "expense_table"}:
                    logger.info(f"[PIPELINE] Recursive scan recovered expense_table on page {pg}")
                    tables.append(reconstruct_table(h_reg))
        
        doc = DocumentStructure(
            regions=regions,
            tables=tables,
            fields=fields,
            claim_id=claim_id or (tokens[0].claim_id if tokens else None),
            document_id=tokens[0].document_id if tokens else None
        )
    else:
        logger.info(f"[PIPELINE] Model-assisted detection found {len(doc.regions)} regions and {len(doc.tables)} tables")
        
        # HYBRID FALLBACK: For each page, if model found nothing, try heuristic detection
        model_pages = {r.page for r in doc.regions}
        all_pages = {t.page for t in tokens}
        missing_pages = all_pages - model_pages
        
        if missing_pages:
            logger.info(f"[PIPELINE] Model missed pages {missing_pages}. Running heuristic detector for these pages...")
            # Filter tokens for missing pages
            missing_tokens = [t for t in tokens if t.page in missing_pages]
            h_regions = detect_regions(missing_tokens)
            for h_reg in h_regions:
                if h_reg.region_type in {"table", "expense_table"}:
                    logger.info(f"[PIPELINE] Heuristic found expense_table on missing page {h_reg.page}")
                    table_region = reconstruct_table(h_reg)
                    doc.tables.append(table_region)
                doc.regions.append(h_reg)

        # HYBRID FALLBACK 2: If a page HAS regions but NO tables, try to find tables using heuristics
        pages_with_tables = {t.page for t in doc.tables}
        pages_to_retry = all_pages - pages_with_tables
        
        for pg in pages_to_retry:
            logger.info(f"[PIPELINE] No tables found on page {pg}. Running heuristic table scanner...")
            page_tokens = [t for t in tokens if t.page == pg]
            h_regions = detect_regions(page_tokens, gap_threshold=15.0)
            for h_reg in h_regions:
                if h_reg.region_type in {"table", "expense_table"}:
                    # Check for overlap with existing regions (usually forms)
                    # If it's a table, we prioritize it
                    table_region = reconstruct_table(h_reg)
                    doc.tables.append(table_region)
                    logger.info(f"[PIPELINE] Heuristic scanner recovered expense_table on page {pg}")


        # For model-detected regions, we still need to run our form extractor
        # AND check if they contain nested tables that the model missed
        all_fields = []
        for region in doc.regions:
            # Try to find tables within any region that isn't already a table
            if region.region_type != "table" and region.region_type != "expense_table":
                # Nested Table Check: Try to find tables within this region using a TIGHTER threshold
                # This helps isolate rows that were merged by the coarser first pass
                sub_regions = detect_regions(region.tokens, gap_threshold=12.0)
                for sub_reg in sub_regions:
                    if sub_reg.region_type in {"table", "expense_table"}:
                        # Prevent duplicate tables if they overlap significantly with existing ones
                        is_duplicate = False
                        for existing_table in doc.tables:
                            # Simple BBox overlap check
                            if abs(sub_reg.bbox[1] - existing_table.bbox[1]) < 20 and abs(sub_reg.bbox[3] - existing_table.bbox[3]) < 20:
                                is_duplicate = True
                                break
                        
                        if not is_duplicate:
                            logger.info(f"[PIPELINE] Found nested expense_table in {region.region_type} on page {region.page}")
                            table_region = reconstruct_table(sub_reg)
                            doc.tables.append(table_region)
                
                # Normal field extraction
                extracted_fields = extract_fields(region)
                all_fields.extend(extracted_fields)
        doc.fields = all_fields

            
    # 4. Semantic Extraction (Region-first model-assisted layer)
    semantic_output = extract_semantics(doc, page_images=page_images, debug_dir=debug_dir, claim_id=claim_id)
    doc.semantic_regions = [region.model_dump() for region in semantic_output.semantic_regions]
    doc.classified_tables = [table.model_dump() for table in semantic_output.classified_tables]
    doc.semantic_field_mapping = semantic_output.semantic_field_mapping
    doc.semantic_table_mapping = semantic_output.semantic_table_mapping
    doc.model_predictions = semantic_output.model_predictions

    # Primary path: use semantic fields and semantic expense rows.
    if semantic_output.semantic_fields:
        doc.normalized_fields = [
            {
                "field": field.canonical_field,
                "canonical_field": field.canonical_field,
                "value": field.value,
                "confidence": field.confidence,
                "bbox": None,
                "page": next((token.page for token in field.source_tokens if token.page is not None), None),
                "source_region_id": field.source_region_id,
                "source_region_type": field.source_region_type,
                "source_tokens": [token.model_dump() for token in field.source_tokens],
                "model_name": field.model_name,
                "extractor_name": field.extractor_name or field.model_name,
                "metadata": field.metadata,
            }
            for field in semantic_output.semantic_fields
        ]
    else:
        doc.normalized_fields = normalize_fields(doc.fields)
        table_fields = normalize_table_fields(doc.tables)
        if table_fields:
            existing_keys = {(f.get("canonical_field"), f.get("page"), f.get("value")) for f in doc.normalized_fields}
            for field in table_fields:
                dedupe_key = (field.get("canonical_field"), field.get("page"), field.get("value"))
                if dedupe_key not in existing_keys:
                    doc.normalized_fields.append(field)
                    existing_keys.add(dedupe_key)

    def _append_local_field(field_name: str, value: str | None, confidence: float = 0.75) -> None:
        if not value:
            return
        text = str(value).strip()
        if not text:
            return
        # Sanitize some common fields before appending
        if field_name == "age":
            # Extract numeric age (e.g., '60 Years', '60 yrs') and ignore trailing currency/policy text
            import re as _re
            m = _re.search(r"(\d{1,3})\s*(years|yrs|year|y)?", text, _re.IGNORECASE)
            if m:
                text = f"{m.group(1)} Years"
            else:
                # fallback: if text looks like DOB, skip age (we prefer DOB elsewhere)
                if _re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text):
                    return

        if field_name == "discharge_date":
            # If value contains a date, extract the first date-like token (DD-MM-YYYY or similar)
            import re as _re
            m = _re.search(r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text)
            if m:
                text = m.group(1)
        # Avoid exact-duplicate canonical fields
        if any(existing.get("canonical_field") == field_name and str(existing.get("value") or "").strip() == text for existing in doc.normalized_fields):
            return

        doc.normalized_fields.append({
            "field": field_name,
            "canonical_field": field_name,
            "value": text,
            "confidence": confidence,
            "bbox": None,
            "page": None,
            "source_region_id": None,
            "source_region_type": "local_extraction",
            "source_tokens": [],
            "model_name": "local-rule",
            "extractor_name": "local-rule",
            "metadata": {"source": "local_backend"},
        })

    all_token_dicts = [token.model_dump() for token in tokens]
    
    # Use ROBUST REGEX-BASED extraction to ensure consistent field extraction
    # WITHOUT sending sensitive data to LLM
    logger.info("[ROBUST_EXTRACTION] Starting comprehensive regex-based field extraction")
    robust_fields = RobustFieldExtractor.extract_from_tokens(all_token_dicts)
    
    # Append all extracted fields
    for field_name, field_value in robust_fields.items():
        if field_value:
            _append_local_field(field_name, field_value, confidence=0.85)
            logger.info(f"[ROBUST_EXTRACTION] Extracted {field_name}: {field_value}")

    semantic_expenses = semantic_output.semantic_table_mapping.get("expense_line_items", []) or []
    if semantic_expenses:
        doc.normalized_expenses = semantic_expenses
    else:
        expenses = normalize_tables(doc.tables)
        region_expenses = normalize_region_expenses(doc.regions)
        if region_expenses:
            expenses.extend(region_expenses)

        deduped_expenses = []
        seen_expenses = set()
        for expense in expenses:
            key = (
                str(expense.get("description", "")).strip().lower(),
                str(expense.get("amount", "")).strip().lower(),
                str(expense.get("page", 0)),
            )
            if key in seen_expenses:
                continue
            seen_expenses.add(key)
            deduped_expenses.append(expense)

        # Filter out aggregate / summary rows that are not line-item charges.
        # Examples: 'admissible amount', 'patient share', 'total', 'net payable', etc.
        AGGREGATE_KEYWORDS = (
            "admissible",
            "patient share",
            "co-pay",
            "copay",
            "total",
            "grand total",
            "net payable",
            "payable",
            "balance",
            "admissible amount",
            "claim amount",
            "amount requested",
            "requested amount",
            "claim requested",
            "total requested",
            "sum insured",
            "previous claims",
            "claim vs",
            "exceeding policy",
            "risk factor",
            "icd-10",
            "snomed",
        )

        filtered_expenses = []
        seen_cat_amount = set()
        seen_category_amounts = {}  # Track all amounts for each category
        
        for e in deduped_expenses:
            desc = str(e.get("description", "")).strip().lower()
            cat = str(e.get("category") or "").strip().lower()
            # Try to parse amount as float for comparisons
            amt = None
            try:
                v = str(e.get("amount", "")).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
                amt = float(v)
            except Exception:
                amt = None

            # If description contains any aggregate keyword, skip as an itemized
            # expense. Also skip very short descriptions that look like labels.
            if any(k in desc for k in AGGREGATE_KEYWORDS) or (len(desc.split()) <= 2 and desc.endswith(":")):
                logger.debug(f"[EXPENSE_FILTER] Skipping aggregate/summary row: {desc}")
                continue

            # If we already have an item with same category+amount, treat this as
            # a duplicate summary row and skip it (helps remove repeated ICU summary rows).
            key_ca = (cat, amt)
            if key_ca in seen_cat_amount:
                logger.debug(f"[EXPENSE_FILTER] Skipping duplicate category+amount row: {cat} / {amt}")
                continue

            # AGGRESSIVE deduplication: if this category already has an entry with this amount,
            # AND the category is not generic (like "Miscellaneous"), skip it as a likely duplicate
            if cat and cat not in {"miscellaneous", "other"}:
                if cat not in seen_category_amounts:
                    seen_category_amounts[cat] = []
                # If this category+amount combo is already there, skip
                if (cat, amt) in seen_category_amounts[cat]:
                    logger.debug(f"[EXPENSE_FILTER] Skipping duplicate category entry: {cat} / {amt}")
                    continue
                seen_category_amounts[cat].append((cat, amt))

            if cat or amt is not None:
                seen_cat_amount.add(key_ca)

            filtered_expenses.append(e)

        doc.normalized_expenses = filtered_expenses

    # Apply semantic table kinds back onto reconstructed tables so downstream
    # canonicalization can distinguish expenses, medications, labs, and diagnoses.
    table_kind_map = {}
    for table in semantic_output.classified_tables:
        region_id = table.source_region_id
        if region_id:
            table_kind_map[region_id] = table.table_kind

    for table in doc.tables:
        semantic_kind = table_kind_map.get(table.region_id)
        if semantic_kind:
            table.table_kind = semantic_kind
    
    # Build canonical claim from normalized fields
    for nf in doc.normalized_fields:
        canonical = nf.get('canonical_field') or nf.get('field')
        if not canonical:
            continue
        path = str(canonical).split('_')
        current = doc.canonical_claim
        for p in path[:-1]:
            # If an existing leaf value is present where we need a dict,
            # overwrite it with a dict to continue building nested structure.
            existing = current.get(p)
            if not isinstance(existing, dict):
                current[p] = {}
            current = current[p]
        current[path[-1]] = nf.get('value')
    
    # 5. Generate Document Isolation Debug Artifacts
    if debug_dir:
        _generate_document_isolation_artifacts(doc, tokens, debug_dir, claim_id)
    
    # 6. Generate Visual Debug Overlays
    if debug_dir:
        try:
            generate_overlays(doc, output_dir=debug_dir, 
                             normalized_fields=doc.normalized_fields, 
                             normalized_expenses=doc.normalized_expenses)
        except Exception as e:
            logger.warning(f"[DEBUG_OVERLAY] Visual debug overlay generation failed (parser continues): {e}")
        
    return doc


def _generate_document_isolation_artifacts(doc: DocumentStructure, tokens: List[Token], debug_dir: str, claim_id: Optional[str]) -> None:
    """Generate debug artifacts showing document isolation.
    
    SAFE: This function never crashes the parser. If artifact generation fails,
    it logs a warning and continues. The parser pipeline always completes.
    """
    import os
    
    try:
        # CRITICAL: Ensure debug directory exists BEFORE writing any artifacts
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            logger.info(f"[DEBUG_ARTIFACT] Ensured debug directory exists: {debug_dir}")
        else:
            logger.warning("[DEBUG_ARTIFACT] debug_dir is empty, skipping artifact generation")
            return
        
        # 1. isolated_documents.json - shows how documents were separated
        try:
            isolated_docs = {}
            for region in doc.regions:
                key = f"{region.claim_id or 'unknown'}|{region.document_id or 'unknown'}"
                if key not in isolated_docs:
                    isolated_docs[key] = {
                        "claim_id": region.claim_id,
                        "document_id": region.document_id,
                        "pages": {}
                    }
                
                page_num = region.page
                if page_num not in isolated_docs[key]["pages"]:
                    isolated_docs[key]["pages"][page_num] = {
                        "page_number": page_num,
                        "token_count": 0,
                        "region_count": 0,
                        "regions": []
                    }
                
                isolated_docs[key]["pages"][page_num]["token_count"] += len(region.tokens)
                isolated_docs[key]["pages"][page_num]["region_count"] += 1
                isolated_docs[key]["pages"][page_num]["regions"].append({
                    "region_type": region.region_type,
                    "region_id": region.region_id,
                    "token_count": len(region.tokens),
                    "bbox": region.bbox,
                    "confidence": region.confidence
                })
            
            isolated_docs_output = {
                "claim_id": claim_id,
                "document_count": len(isolated_docs),
                "documents": [
                    {
                        "claim_id": val["claim_id"],
                        "document_id": val["document_id"],
                        "page_count": len(val["pages"]),
                        "total_regions": sum(p["region_count"] for p in val["pages"].values()),
                        "total_tokens": sum(p["token_count"] for p in val["pages"].values()),
                        "pages": sorted(val["pages"].items(), key=lambda x: x[0])
                    }
                    for val in isolated_docs.values()
                ]
            }
            
            artifact_path = os.path.join(debug_dir, "10_isolated_documents.json")
            with open(artifact_path, "w") as f:
                json.dump(isolated_docs_output, f, indent=2)
            logger.info(f"[DEBUG_ARTIFACT] Generated isolated_documents.json: {len(isolated_docs)} document-clusters")
        
        except Exception as e:
            logger.warning(f"[DEBUG_ARTIFACT] Failed to generate isolated_documents.json: {e}")
        
        # 2. grouped_pages.json - shows token grouping by (claim_id, document_id, page)
        try:
            grouped_pages = {}
            for token in tokens:
                key = (token.claim_id or "unknown", token.document_id or "unknown", token.page)
                if key not in grouped_pages:
                    grouped_pages[key] = {
                        "claim_id": token.claim_id,
                        "document_id": token.document_id,
                        "page_number": token.page,
                        "token_count": 0,
                        "x_range": [float('inf'), float('-inf')],
                        "y_range": [float('inf'), float('-inf')]
                    }
                
                grouped_pages[key]["token_count"] += 1
                grouped_pages[key]["x_range"][0] = min(grouped_pages[key]["x_range"][0], token.x0)
                grouped_pages[key]["x_range"][1] = max(grouped_pages[key]["x_range"][1], token.x1)
                grouped_pages[key]["y_range"][0] = min(grouped_pages[key]["y_range"][0], token.y0)
                grouped_pages[key]["y_range"][1] = max(grouped_pages[key]["y_range"][1], token.y1)
            
            grouped_pages_output = {
                "claim_id": claim_id,
                "group_count": len(grouped_pages),
                "groups": [
                    {
                        "claim_id": val["claim_id"],
                        "document_id": val["document_id"],
                        "page_number": val["page_number"],
                        "token_count": val["token_count"],
                        "bbox": [val["x_range"][0], val["y_range"][0], val["x_range"][1], val["y_range"][1]]
                    }
                    for val in sorted(grouped_pages.values(), key=lambda x: (x["claim_id"], x["document_id"], x["page_number"]))
                ]
            }
            
            artifact_path = os.path.join(debug_dir, "11_grouped_pages.json")
            with open(artifact_path, "w") as f:
                json.dump(grouped_pages_output, f, indent=2)
            logger.info(f"[DEBUG_ARTIFACT] Generated grouped_pages.json: {len(grouped_pages)} document-page groups")
        
        except Exception as e:
            logger.warning(f"[DEBUG_ARTIFACT] Failed to generate grouped_pages.json: {e}")
    
    except Exception as e:
        logger.warning(f"[DEBUG_ARTIFACT] Debug artifact generation failed (parser continues): {e}")




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
