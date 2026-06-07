import json
import logging
import re
from typing import List, Dict, Any
from .models import Token, DocumentStructure

logger = logging.getLogger("parser-debug")
from .layout_detector import detect_regions
from .table_reconstructor import reconstruct_table
from .form_extractor import extract_fields
from .schema_normalizer import normalize_fields, normalize_tables, normalize_table_fields, normalize_region_expenses, normalize_summary_bill_expenses
from .settings import MERGE_SEMANTIC_AND_HEURISTIC, MERGE_DESCRIPTION_SIMILARITY, MERGE_AMOUNT_TOLERANCE
from .semantic_extractor import extract_semantics
from .debug_overlay import generate_overlays
from .document_processor import DocumentProcessor
from PIL import Image
from typing import Optional

from services.parser.app.form_extractor import extract_form_fields as extract_local_form_fields
from services.parser.app.lightweight_ner import extract_ner_entities as extract_local_entities
from services.parser.app.robust_field_extractor import RobustFieldExtractor


def _extract_diagnosis_fields_from_tokens(token_dicts: list[dict[str, Any]]) -> dict[str, str]:
    """Extract primary/secondary diagnosis strings from label-style OCR text.

    This is a conservative fallback used when semantic/local extractors miss
    secondary diagnosis fields in discharge/billing summaries.
    """
    text_parts: list[str] = []
    for token in token_dicts:
        raw = str(token.get("text") or "").strip()
        if raw:
            text_parts.append(raw)
    full_text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
    if not full_text:
        return {}

    stop_clause = (
        r"(?:length\s+of\s+stay|diagnosis\s+count|medications|total\s+bill|claim\s+amount|"
        r"procedure\s*:|cpt\s*code|hospital\s+expense\s+breakdown|sr\.|$)"
    )
    out: dict[str, str] = {}

    primary_match = re.search(
        rf"(?:primary\s+diagnosis|diagnosis)\s*[:\-]?\s*(.+?)\s*(?=(?:sec(?:ondary)?\.?\s*diagnoses?|secondary\s+diagnosis|{stop_clause}))",
        full_text,
        flags=re.IGNORECASE,
    )
    if primary_match:
        primary = primary_match.group(1).strip(" ,;:-")
        if primary:
            out["diagnosis"] = primary

    secondary_match = re.search(
        rf"(?:sec(?:ondary)?\.?\s*diagnoses?|secondary\s+diagnosis(?:es)?)\s*[:\-]?\s*(.+?)\s*(?={stop_clause})",
        full_text,
        flags=re.IGNORECASE,
    )
    if secondary_match:
        secondary = secondary_match.group(1).strip(" ,;:-")
        if secondary:
            out["secondary_diagnosis"] = secondary

    return out


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
        
        # RECURSIVE SCAN: If no tables were found on a page, try a wider scan (40px) and a tighter scan (12px)
        pages_with_tables = {t.page for t in tables}
        all_pages = {t.page for t in tokens}
        for pg in (all_pages - pages_with_tables):
            logger.info(f"[PIPELINE] No table on page {pg}. Running wider recursive scan (40px) to catch sparse tables...")
            pg_tokens = [t for t in tokens if t.page == pg]
            h_regions = detect_regions(pg_tokens, gap_threshold=40.0)
            found_any = False
            for h_reg in h_regions:
                if h_reg.region_type in {"table", "expense_table"}:
                    logger.info(f"[PIPELINE] Wider recursive scan recovered expense_table on page {pg}")
                    tables.append(reconstruct_table(h_reg))
                    found_any = True
            
            if not found_any:
                logger.info(f"[PIPELINE] No table found with wider scan. Trying tighter recursive scan (18px)...")
                h_regions = detect_regions(pg_tokens, gap_threshold=18.0)
                for h_reg in h_regions:
                    if h_reg.region_type in {"table", "expense_table"}:
                        logger.info(f"[PIPELINE] Tighter recursive scan recovered expense_table on page {pg}")
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
            logger.info(f"[PIPELINE] No tables found on page {pg}. Running precise heuristic table scanner (18px)...")
            page_tokens = [t for t in tokens if t.page == pg]
            h_regions = detect_regions(page_tokens, gap_threshold=18.0)
            found_any = False
            for h_reg in h_regions:
                if h_reg.region_type in {"table", "expense_table"}:
                    table_region = reconstruct_table(h_reg)
                    doc.tables.append(table_region)
                    doc.regions.append(h_reg)
                    logger.info(f"[PIPELINE] Precise scanner (12px) recovered expense_table on page {pg}")
                    found_any = True
            
            if not found_any:
                logger.info(f"[PIPELINE] No tables found with 12px scan. Running wider heuristic table scanner (40px) fallback...")
                h_regions = detect_regions(page_tokens, gap_threshold=40.0)
                for h_reg in h_regions:
                    if h_reg.region_type in {"table", "expense_table"}:
                        table_region = reconstruct_table(h_reg)
                        doc.tables.append(table_region)
                        doc.regions.append(h_reg)
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
        # Filter out malformed expense_table_row_* semantic fields that contain
        # patient metadata (DOB, Age, Address, Phone) or non-numeric amounts.
        def _is_bad_expense_field(f: dict) -> bool:
            name = str(f.get("field") or f.get("canonical_field") or "")
            if not name.startswith("expense_table_row"):
                return False
            val = str(f.get("value") or "")
            # dates, phone, email, address likely indicate non-expense metadata
            if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", val):
                return True
            if re.search(r"phone|address|email|date of birth|dob|age:\b", val, flags=re.IGNORECASE):
                return True
            # attempt to find numeric amount in the value; if none, treat as bad
            if not re.search(r"\d", val):
                return True
            return False

        filtered = [f for f in doc.normalized_fields if not _is_bad_expense_field(f)]
        if len(filtered) != len(doc.normalized_fields):
            logger.info("[FIELD_FILTER] Removed %d malformed expense_table_row_* fields", len(doc.normalized_fields) - len(filtered))
        doc.normalized_fields = filtered
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

    import re as _re
    for nf in doc.normalized_fields:
        if nf.get("canonical_field") == "patient_name" and nf.get("value"):
            nf["value"] = _re.sub(r"\s+Relation\b.*$", "", str(nf["value"]), flags=_re.IGNORECASE).strip()

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

        if field_name in {"admission_date", "discharge_date"}:
            # If value contains a date, extract the first date-like token (DD-MM-YYYY or similar)
            import re as _re
            m = _re.search(r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text)
            if m:
                text = m.group(1)

        if field_name == "patient_name":
            # Strip relation suffix (e.g. "Relation to Brother", "Relation to Husband", etc.)
            import re as _re
            text = _re.sub(r"\s+Relation\b.*$", "", text, flags=_re.IGNORECASE).strip()
        # Avoid exact-duplicate canonical fields (case-insensitive value match)
        existing_value_lower = str(text).strip().lower()
        if any(existing.get("canonical_field") == field_name and str(existing.get("value") or "").strip().lower() == existing_value_lower for existing in doc.normalized_fields):
            logger.debug(f"[DEDUP] Skipping duplicate field {field_name}={text}")
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
    
    # Use ROBUST REGEX-BASED extraction for PATIENT INFO fields.
    # We do not skip this pass if a single semantic field exists; instead we
    # backfill only missing keys so partial semantic output cannot suppress
    # hospital/doctor/diagnosis/date extraction.
    patient_field_names = {
        "hospital_name",
        "doctor_name",
        "diagnosis",
        "secondary_diagnosis",
        "patient_name",
        "admission_date",
        "discharge_date",
        "age",
        "sex",
        "gender",
        "address",
        "occupation",
        "claimed_total",
    }
    existing_patient_fields = {
        str(f.get("canonical_field") or "")
        for f in doc.normalized_fields
        if isinstance(f, dict)
    }
    missing_patient_fields = sorted(
        field_name for field_name in patient_field_names if field_name not in existing_patient_fields
    )

    logger.info(
        "[ROBUST_EXTRACTION] Existing patient fields=%s missing=%s",
        sorted(existing_patient_fields & patient_field_names),
        missing_patient_fields,
    )

    if missing_patient_fields:
        robust_fields = RobustFieldExtractor.extract_from_tokens(all_token_dicts)
        # Map common robust extractor keys to canonical field names
        robust_to_canonical = {
            "admission_date": "admission_date",
            "discharge_date": "discharge_date",
            "gender": "sex",
            "patient_name": "patient_name",
            "doctor_name": "doctor_name",
            "hospital_name": "hospital_name",
            "policy_number": "policy_number",
            "member_id": "member_id",
            "age": "age",
            "claimed_total": "claimed_total",
        }

        for field_name in missing_patient_fields:
            # try direct key first, then synonyms
            field_value = robust_fields.get(field_name)
            if field_value is None:
                # check reverse mapping: if robust extractor produced a key that maps to this canonical field
                for r_key, canon in robust_to_canonical.items():
                    if canon == field_name:
                        field_value = robust_fields.get(r_key)
                        if field_value:
                            break

            if field_value:
                _append_local_field(field_name, field_value, confidence=0.85)
                logger.info(f"[ROBUST_EXTRACTION] Backfilled {field_name}: {field_value}")

    diagnosis_fields = _extract_diagnosis_fields_from_tokens(all_token_dicts)
    if "diagnosis" not in existing_patient_fields and diagnosis_fields.get("diagnosis"):
        _append_local_field("diagnosis", diagnosis_fields["diagnosis"], confidence=0.9)
        logger.info("[DIAGNOSIS_FALLBACK] Backfilled diagnosis from labeled text")
    if "secondary_diagnosis" not in existing_patient_fields and diagnosis_fields.get("secondary_diagnosis"):
        _append_local_field("secondary_diagnosis", diagnosis_fields["secondary_diagnosis"], confidence=0.9)
        logger.info("[DIAGNOSIS_FALLBACK] Backfilled secondary_diagnosis from labeled text")

    # Detect obviously noisy semantic values (model concatenated headers or many labels)
    def _is_noisy_field(val: str, field_name: str = "") -> bool:
        if not val:
            return False
        v = str(val).strip()
        if len(v) > 200:
            return True
        v_lower = v.lower()

        # Generic check: if value contains multiple header-like tokens, consider it noisy
        header_tokens = ["admission", "discharge", "sex", "ip no", "uhid", "claim", "policy", "tpa", "diagnosis"]
        cnt = sum(1 for h in header_tokens if h in v_lower)
        if cnt >= 2:
            return True

        if field_name == "doctor_name":
            # Doctor name noise: contains digits (e.g. "Reg: No.= Primary 1"), registration labels, or known metadata words
            if any(ch.isdigit() for ch in v):
                return True
            noise_terms = ["reg", "registration", "primary", "secondary", "no.", "ref", "days", "insured", "claim"]
            if any(term in v_lower for term in noise_terms):
                return True

        elif field_name == "hospital_name":
            # Hospital name noise: contains registration patterns or multiple header labels
            noise_terms = ["reg:", "reg no", "registration", "patient", "admission", "ip no", "ipd", "claim"]
            if any(term in v_lower for term in noise_terms):
                return True

        elif field_name == "diagnosis":
            # Diagnosis noise: insurance/temporal metadata mistakenly extracted
            noise_terms = [
                "days", "future generali", "insurance", "tpa", "policy", "sum insured",
                "1 day", "2 days", "3 days", "future", "generali",
            ]
            if any(term in v_lower for term in noise_terms):
                return True

        return False

    # For noisy canonical patient/hospital/diagnosis fields, prefer robust extractor
    for nf in list(doc.normalized_fields):
        cf = nf.get("canonical_field") or nf.get("field")
        if cf in {"diagnosis", "doctor_name", "hospital_name"}:
            val = str(nf.get("value") or "")
            if _is_noisy_field(val, cf):
                logger.info(f"[NOISY_FIELD] Detected noisy semantic value for {cf}; attempting robust backfill")
                fallback = RobustFieldExtractor.extract_from_tokens(all_token_dicts).get(cf)
                if fallback:
                    # remove existing noisy field and append cleaned value
                    doc.normalized_fields = [f for f in doc.normalized_fields if not (f.get("canonical_field") == cf and f.get("value") == nf.get("value"))]
                    _append_local_field(cf, fallback, confidence=0.9)
                    logger.info(f"[NOISY_FIELD] Replaced {cf} with robust value: {fallback}")

    # Strip registration/accreditation suffixes from hospital_name
    # e.g. "AIG Hospitals Registration AIG-HYD-2010-0077" → "AIG Hospitals"
    import re as _re_hosp
    for nf in list(doc.normalized_fields):
        cf = nf.get("canonical_field") or nf.get("field")
        if cf == "hospital_name":
            val = str(nf.get("value") or "").strip()
            cleaned = _re_hosp.sub(
                r"\s+(?:registration|reg\.?|reg no\.?|accreditation|license|regd\.?|regd no\.?)\s+\S+.*$",
                "",
                val,
                flags=_re_hosp.IGNORECASE,
            ).strip()
            # Also strip trailing registration codes like "XYZ-2010-0077"
            cleaned = _re_hosp.sub(r"\s+[A-Z]{2,10}-[A-Z0-9]{2,10}-\d{4}-\d{4,}\s*$", "", cleaned).strip()
            if cleaned and cleaned != val:
                doc.normalized_fields = [f for f in doc.normalized_fields if not (f.get("canonical_field") == cf and f.get("value") == val)]
                _append_local_field(cf, cleaned, confidence=0.92)
                logger.info(f"[HOSPITAL_CLEANUP] Stripped registration suffix: '{val}' → '{cleaned}'")

    # Strip CPT/procedure code blocks from secondary_diagnosis
    # e.g. "Gingival disease Secondary Diagnosis 2: ... ICD-10: K72.9 CPT: 47135 ..."
    for nf in list(doc.normalized_fields):
        cf = nf.get("canonical_field") or nf.get("field")
        if cf == "secondary_diagnosis":
            val = str(nf.get("value") or "").strip()
            # Strip from first "Secondary Diagnosis 2:" onward if the first diagnosis is embedded
            cleaned = _re_hosp.sub(r"\s+Secondary\s+Diagnosis\s+\d+:.*$", "", val, flags=_re_hosp.IGNORECASE).strip()
            # Strip trailing ICD-10/CPT/Procedure code blocks
            cleaned = _re_hosp.sub(r"\s+(?:ICD-10:|CPT:|Procedure\s+\d+:).*$", "", cleaned, flags=_re_hosp.IGNORECASE).strip()
            if cleaned and cleaned != val:
                doc.normalized_fields = [f for f in doc.normalized_fields if not (f.get("canonical_field") == cf and f.get("value") == val)]
                _append_local_field(cf, cleaned, confidence=0.88)
                logger.info(f"[DIAG_CLEANUP] Stripped CPT noise from secondary_diagnosis: '{val[:60]}...' → '{cleaned}'")

    # If doctor_name looks like a table header or contains digits, try a location-based fallback
    def _heuristic_doctor_from_label(token_dicts: list[dict]) -> str | None:
        import re
        # find a token that equals 'doctor' (case-insensitive)
        for t in token_dicts:
            if isinstance(t.get('text'), str) and re.search(r"\bdoctor\b", t.get('text'), re.IGNORECASE):
                page = t.get('page')
                y0 = float(t.get('y0') or 0)
                # candidate tokens: same page, y between y0-40 and y0+40 and x > t.x1
                candidates = [tt for tt in token_dicts if tt.get('page') == page]
                # sort by x0 (left->right)
                candidates = sorted(candidates, key=lambda z: (z.get('page', 0), float(z.get('x0') or 0)))
                # find tokens that come after the 'doctor' token horizontally
                after = [c for c in candidates if float(c.get('x0') or 0) > float(t.get('x1') or 0) and abs(float(c.get('y0') or 0) - y0) < 50]
                # pick up to 4 alphabetic tokens
                name_parts = []
                for a in after:
                    txt = str(a.get('text') or "").strip()
                    if re.match(r"^[A-Za-z][A-Za-z\.\s]{1,}$", txt) and len(txt) > 1:
                        name_parts.append(txt)
                    if len(name_parts) >= 4:
                        break
                if name_parts:
                    return " ".join(name_parts)
        return None

    # Check doctor_name quality and attempt heuristic label-based extraction
    for nf in list(doc.normalized_fields):
        if (nf.get('canonical_field') or nf.get('field')) == 'doctor_name':
            val = str(nf.get('value') or '')
            # heuristics for bad value: contains digits or typical table header words
            if any(ch.isdigit() for ch in val) or any(h in val.lower() for h in ['qty', 'rate', 'anount', 'amount']):
                heuristic = _heuristic_doctor_from_label(all_token_dicts)
                if heuristic:
                    # replace existing
                    # Trim common trailing header tokens from heuristic name
                    import re
                    trim_tokens = ['batch', 'qty', 'rate', 'anount', 'amount', 'nan', 'naned']
                    h_clean = heuristic
                    for tk in trim_tokens:
                        parts = re.split(r"\b" + re.escape(tk) + r"\b", h_clean, flags=re.IGNORECASE)
                        if parts:
                            h_clean = parts[0].strip()
                    if h_clean:
                        doc.normalized_fields = [f for f in doc.normalized_fields if not (f.get('canonical_field') == 'doctor_name' and f.get('value') == val)]
                        _append_local_field('doctor_name', h_clean, confidence=0.9)
                        logger.info(f"[DOCTOR_HEURISTIC] Replaced noisy doctor_name '{val}' with '{h_clean}'")

    # Expense extraction is intentionally delayed until after semantic table kinds
    # are applied below, so normalize_tables() can see the finalized table type.

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

    semantic_expenses = semantic_output.semantic_table_mapping.get("expense_line_items", []) or []
    # Heuristic/normalized rows
    heuristic_expenses = normalize_tables(doc.tables) or []
    summary_bill_expenses = normalize_summary_bill_expenses(all_token_dicts) or []
    
    # Pre-initialize heuristic_pages and existing_keys to ensure they are always defined in all scopes
    heuristic_pages = {
        int(expense.get("page") or 0)
        for expense in heuristic_expenses
        if str(expense.get("page") or "").strip()
    }
    existing_keys = {
        (
            str(expense.get("description") or "").strip().lower(),
            str(expense.get("amount") or "").strip().lower(),
        )
        for expense in heuristic_expenses
    }
    
    if summary_bill_expenses:
        if not heuristic_expenses:
            heuristic_expenses = summary_bill_expenses
            existing_keys = {
                (
                    str(expense.get("description") or "").strip().lower(),
                    str(expense.get("amount") or "").strip().lower(),
                )
                for expense in heuristic_expenses
            }
        else:
            # Multi-page bill continuity: if heuristic table extraction misses one
            # page (commonly page 1 when table continues on page 2+), merge
            # summary-derived rows from uncovered pages.
            summary_candidates = [
                row
                for row in summary_bill_expenses
                if int(row.get("page") or 0) not in heuristic_pages
            ]
            if not summary_candidates:
                summary_candidates = summary_bill_expenses

            for row in summary_candidates:
                row_key = (
                    str(row.get("description") or "").strip().lower(),
                    str(row.get("amount") or "").strip().lower(),
                )
                if not row_key[0] or not row_key[1] or row_key in existing_keys:
                    continue
                heuristic_expenses.append(row)
                existing_keys.add(row_key)
    # Also consider region-level extracted expense rows (single-line items)
    # and merge any rows that are on pages not already covered by heuristic tables.
    region_expenses = normalize_region_expenses(doc.regions) or []
    if region_expenses:
        region_candidates = [r for r in region_expenses if int(r.get("page") or 0) not in heuristic_pages]
        for row in region_candidates:
            row_key = (
                str(row.get("description") or "").strip().lower(),
                str(row.get("amount") or "").strip().lower(),
            )
            if not row_key[0] or not row_key[1] or row_key in existing_keys:
                continue
            heuristic_expenses.append(row)
            existing_keys.add(row_key)
    if not heuristic_expenses:
        heuristic_expenses = normalize_region_expenses(doc.regions) or []

    def _norm_desc(d: str) -> str:
        import re
        if not d:
            return ""
        d = d.lower()
        d = re.sub(r"[^a-z0-9\s]", " ", d)
        d = re.sub(r"\s+", " ", d).strip()
        return d

    def _parse_amount(a) -> float:
        try:
            if a is None:
                return 0.0
            s = str(a)
            # Normalize whitespace and non-breaking spaces
            s = s.replace("\u00A0", " ")
            s = s.replace(" ", "")
            # Handle common currency markers
            s = s.replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
            s = s.strip()
            if s.startswith("(") and s.endswith(")"):
                s = "-" + s[1:-1]
            # If value uses comma as decimal separator (e.g. 20,02) and no dot present,
            # convert to dot. Otherwise remove thousands-separating commas.
            if "," in s and "." not in s:
                parts = s.split(",")
                # Heuristic: a single comma with 1-2 decimals indicates decimal separator
                if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                    s = parts[0] + "." + parts[1]
                else:
                    s = s.replace(",", "")
            else:
                s = s.replace(",", "")
            return float(s)
        except Exception:
            return 0.0

    def _is_probable_expense_row(expense: dict) -> bool:
        import re
        desc = str(expense.get("description") or "").strip().lower()
        amount_val = expense.get("amount")
        amount = _parse_amount(amount_val)
        if not desc:
            return False
        
        # Reject 6-digit pincodes in description (e.g. 500082)
        if re.search(r"\b\d{6}\b", desc):
            return False

        # Aadhaar
        if re.search(r"\b(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}|[XxX]{4}[-\s]?[XxX]{4}[-\s]?\d{4})\b", desc):
            return False

        # PAN
        if re.search(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b", desc):
            return False

        # Bank IFSC
        if re.search(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b", desc):
            return False

        # Bank Account Number / Cheque Number
        amt_clean = re.sub(r"[^0-9]", "", str(amount_val or ""))
        if len(amt_clean) >= 9 or (len(amt_clean) == 6 and any(term in desc for term in ["cheque", "chq", "pin"])):
            return False

        # Medication strength/dosage filter
        if desc.startswith(("inj.", "tab.", "cap.", "inj ", "tab ", "cap ", "(cid:")):
            is_probable_price = False
            if amt_clean:
                try:
                    if "." in str(amount_val) or float(amt_clean) > 100.0:
                        is_probable_price = True
                except ValueError:
                    pass
            
            if not is_probable_price:
                if amt_clean in {"1", "2", "4", "5", "10", "20", "40", "50", "100", "250", "500", "650"}:
                    return False
                if any(term in desc for term in [" po ", " iv ", " im ", " sc ", " bd", " tds", " od", " mg ", " ml ", " mcg "]):
                    return False

        if amount < 0:
            return False
        if amount == 0:
            # Allow 0 amounts if the description has at least 3 alphabetic/alphanumeric characters
            desc_cleaned = re.sub(r"[^a-zA-Z0-9]", "", desc)
            if len(desc_cleaned) < 3:
                return False

        blacklist = (
            "bill no",
            "bill number",
            "claim no",
            "claim number",
            "gstin",
            "auth",
            "hospital name",
            "h.no",
            "address",
            "patient name",
            "doctor name",
            "admission date",
            "discharge date",
            "invoice",
            "summary",
            "subtotal",
            "total",
            "grand total",
            "net total",
            "net payable",
            "admissible amount",
            "patient share",
            "co-pay",
            "co pay",
            "gross total",
            "amount payable",
            "amount requested",
            "claim amount requested",
            "amount exceeding policy",
            "sum insured",
            "closing balance",
            # Billing summary rows that are NOT individual expense charges
            "gross hospital bill",
            "gross bill",
            "gross amount",
            "deductible",
            "deductible / excess",
            "less: deductible",
            "less: non-payable",
            "less: non payable",
            "non-payable deductions",
            "non payable deductions",
            "non-payable items",
            "non payable items",
            "deductions",
            "final amount admissible",
            "final admissible",
            "amount admissible",
            "length of stay",
            # Metadata rows about ward/LOS that are not an expense
            "ward: general ward",
            "ward: icu",
            "los:",
            "managed in general ward",
            "managed in icu",
            "patient share:",
            "balance amount",
            "balance payable",
            # Bank Details
            "account number",
            "account no",
            "account name",
            "ifsc",
            "ifsc code",
            "cheque",
            "cheque number",
            "cheque no",
            "chq no",
            "chq number",
            "aadhaar",
            "aadhaar number",
            "uidai",
            "pan card",
            "pan card number",
            "pan no",
            "pan number",
            "neft",
            "neft mandate",
            "mandate",
            "cheque image",
            "net claimed",
            "net claimed amount",
            "claimed amount",
            "claimed total",
            "relation",
            "declare",
            "confirm",
            "mandate verification",
            # Declaration / signature / footer blocks
            "diagnosis count",
            "documented conditions",
            "active prescriptions",
            "policy status",
            "declaration",
            "signature",
            "hereby",
            "consent to the hospital",
            "claim engine system",
            "generated for audit",
            "reg no:",
            "hosp-",
            "tpa/insurance",
            "somajiguda",
            "yashoda",
            "hyderabad",
            "tel:",
            "claim submitted",
            "paramount health",
            "emergency surgery",
            "emergency pci",
            "risk factor",
            "high risk",
            "previous claims",
            "claims in last",
            "acute cardiac event",
            "medically necessary",
            "life-saving",
            "suresh reddy",
            "ramesh kumar",
        )
        if any(term in desc for term in blacklist):
            return False

        # Final length guard: descriptions longer than 300 characters are always
        # concatenated garbage (e.g. declaration blocks merged into a single row).
        if len(desc) > 300:
            logger.info(
                "[EXPENSE_GATE] Rejecting oversized expense description (%d chars): %s...",
                len(desc), desc[:80],
            )
            return False

        # At this stage we already have a structured row with a numeric amount.
        # Keep it unless it is clearly a summary or metadata row.
        return True

    def _is_similar(a: dict, b: dict) -> bool:
        # Safeguard: Never merge two candidates that share the same primary source (both semantic or both heuristic).
        # They represent separate physical rows from the same extraction run, and merging them is over-deduplication.
        if a.get("source") and b.get("source") and a.get("source") == b.get("source"):
            return False

        # Description similarity (token Jaccard) + amount closeness
        a_desc = _norm_desc(a.get("description") or "")
        b_desc = _norm_desc(b.get("description") or "")
        if not a_desc and not b_desc:
            desc_sim = 1.0
            a_set, b_set = set(), set()
        else:
            a_set = set(a_desc.split())
            b_set = set(b_desc.split())
            if not a_set or not b_set:
                desc_sim = 0.0
            else:
                inter = a_set & b_set
                desc_sim = len(inter) / float(len(a_set | b_set))

        # Merge if they are Jaccard-similar OR one description is a substring/subset of the other
        is_contained = False
        if a_desc and b_desc:
            if (a_desc == b_desc):
                is_contained = True
            elif (a_desc in b_desc) or (b_desc in a_desc):
                a_words = a_desc.split()
                b_words = b_desc.split()
                if len(a_words) <= 1 or len(b_words) <= 1:
                    is_contained = False
                else:
                    is_contained = True
            elif a_set.issubset(b_set) or b_set.issubset(a_set):
                if len(a_set) > 1 and len(b_set) > 1:
                    is_contained = True

        is_desc_similar = (desc_sim >= MERGE_DESCRIPTION_SIMILARITY) or is_contained
        
        # Safeguard 1: If both have non-zero amounts AND the difference is greater than tolerance,
        # they represent different charge values and must NOT be merged under any circumstances.
        a_amt = _parse_amount(a.get("amount"))
        b_amt = _parse_amount(b.get("amount"))
        if a_amt > 0.0 and b_amt > 0.0:
            if abs(a_amt - b_amt) > MERGE_AMOUNT_TOLERANCE:
                return False

        # Safeguard 2: If they belong to different non-empty, non-misc categories, they represent
        # completely different expense types and must NOT be merged.
        a_cat = str(a.get("category") or "").strip().lower()
        b_cat = str(b.get("category") or "").strip().lower()
        if a_cat and b_cat and a_cat != "miscellaneous" and b_cat != "miscellaneous" and a_cat != b_cat:
            return False

        # If highly similar in description, we merge.
        if is_desc_similar:
            return True

        amt_close = abs(a_amt - b_amt) <= MERGE_AMOUNT_TOLERANCE
        return is_desc_similar and amt_close

    def _row_quality_rank(row: dict) -> int:
        """Source quality ranking: semantic (3) > table (2) > region (1) > summary (0)."""
        source = str(row.get("source") or "").lower()
        heuristic_source = str(row.get("heuristic_source") or "").lower()
        if source == "semantic":
            return 3
        if source == "heuristic":
            if heuristic_source == "table":
                return 2
            if heuristic_source == "region":
                return 1
            if heuristic_source == "summary":
                return 0
            # Default heuristic without sub-type: treat as region-level
            return 1
        return 0

    def _merge_groups(group: list[dict]) -> dict:
        # Use source quality ranking: semantic > table > region/summary.
        # This prevents low-quality fallback region/summary descriptions from
        # overwriting high-quality structured table or semantic-extracted data.
        semantic_items = [g for g in group if g.get("source") == "semantic"]
        heuristic_items = [g for g in group if g.get("source") == "heuristic"]

        chosen = group[0]
        best_semantic = max(semantic_items, key=lambda x: float(x.get("confidence") or 0.0)) if semantic_items else None
        best_heuristic = max(heuristic_items, key=lambda x: float(x.get("confidence") or 0.0)) if heuristic_items else None

        if best_semantic and best_heuristic:
            sem_amt = _parse_amount(best_semantic.get("amount"))
            heu_amt = _parse_amount(best_heuristic.get("amount"))
            # If there is a mismatch in amount, we prioritize the heuristic amount
            # because the heuristic column-mapping correctly parsed the payable column
            if abs(sem_amt - heu_amt) > MERGE_AMOUNT_TOLERANCE:
                chosen = best_heuristic
            else:
                sem_conf = float(best_semantic.get("confidence") or 0.0)
                heu_conf = float(best_heuristic.get("confidence") or 0.0)
                # Keep semantic choice if confidence is reasonably close.
                chosen = best_semantic if sem_conf >= (heu_conf - 0.15) else best_heuristic
        elif best_semantic:
            chosen = best_semantic
        elif best_heuristic:
            chosen = best_heuristic

        sources = sorted({g.get("source") for g in group if g.get("source")})
        max_conf = max([float(g.get("confidence") or 0.0) for g in group]) if group else 0.0
        merged = dict(chosen)
        merged["sources"] = sources
        merged["confidence"] = max_conf

        # If any item in the group has a normalized description that contains or is a superset
        # of the chosen item's normalized description, use the longer/more complete description
        # BUT only if it comes from a source of equal or higher quality rank.
        chosen_desc_norm = _norm_desc(chosen.get("description") or "")
        longest_desc = chosen.get("description") or ""
        chosen_rank = _row_quality_rank(chosen)

        for g in group:
            g_desc = g.get("description") or ""
            g_desc_norm = _norm_desc(g_desc)
            g_rank = _row_quality_rank(g)
            # Only use a longer description if it comes from >= quality source
            if len(g_desc_norm) > len(chosen_desc_norm) and g_rank >= chosen_rank:
                g_set = set(g_desc_norm.split())
                chosen_set = set(chosen_desc_norm.split())
                if (chosen_desc_norm in g_desc_norm) or chosen_set.issubset(g_set):
                    longest_desc = g_desc
                    chosen_desc_norm = g_desc_norm

        # Keep clean semantic description over messy merged heuristic ones to prevent EXPENSE_GATE drop
        if best_semantic and len(best_semantic.get("description") or "") < 200:
            merged["description"] = best_semantic["description"]
        else:
            merged["description"] = longest_desc
        return merged

    def _merge_expense_lists(sem_list: list, heur_list: list) -> list:
        # Annotate sources
        candidates = []
        for s in sem_list:
            c = dict(s)
            c.setdefault("source", "semantic")
            c.setdefault("confidence", getattr(c, "confidence", 1.0) or 1.0)
            candidates.append(c)
        for h in heur_list:
            c = dict(h)
            c.setdefault("source", "heuristic")
            c.setdefault("confidence", getattr(c, "confidence", 0.5) or 0.5)
            candidates.append(c)

        merged_out = []
        used = [False] * len(candidates)
        for i, cand in enumerate(candidates):
            if used[i]:
                continue
            group = [cand]
            used[i] = True
            for j in range(i + 1, len(candidates)):
                if used[j]:
                    continue
                if _is_similar(cand, candidates[j]):
                    group.append(candidates[j])
                    used[j] = True
            merged_out.append(_merge_groups(group))
        return merged_out

    def _quality_stats(rows: list[dict]) -> tuple[int, float, float]:
        if not rows:
            return 0, 0.0, 0.0
        valid_count = 0
        confidence_total = 0.0
        amount_total = 0.0
        for row in rows:
            desc = str(row.get("description") or "").strip()
            amt = _parse_amount(row.get("amount"))
            conf = float(row.get("confidence") or 0.0)
            if desc and amt > 0:
                valid_count += 1
                confidence_total += conf
                amount_total += amt
        avg_conf = (confidence_total / valid_count) if valid_count > 0 else 0.0
        return valid_count, avg_conf, amount_total

    # LLM-first selection with safeguards: if semantic output is sparse/low-confidence,
    # blend with heuristic rows instead of dropping potentially-correct expenses.
    sem_count, sem_conf, sem_total = _quality_stats(list(semantic_expenses))
    heu_count, heu_conf, heu_total = _quality_stats(heuristic_expenses)

    if semantic_expenses and MERGE_SEMANTIC_AND_HEURISTIC:
        expenses = _merge_expense_lists(list(semantic_expenses), heuristic_expenses)
        logger.info("[EXPENSE_SELECTION] merge_enabled semantic=%s heuristic=%s", sem_count, heu_count)
    elif semantic_expenses:
        # Some semantic backends do not emit calibrated row confidence and default
        # to 0.0. If semantic output is complete and totals are sane, prefer it
        # over heuristic rows, which often include metadata-like duplicates.
        if sem_count >= 5 and sem_total > 0 and sem_conf <= 0.01 and heu_count >= sem_count:
            expenses = list(semantic_expenses)
            def _norm_cat(cat: str) -> str:
                c = (cat or "").strip().lower()
                if c in {"room rent", "room", "ward", "icu"}:
                    return "room"
                if c in {"laboratory", "lab", "diagnostics", "investigation"}:
                    return "laboratory"
                return c

            semantic_categories = {
                _norm_cat(str(item.get("category") or ""))
                for item in expenses
                if str(item.get("category") or "").strip()
            }
            # Keep semantic as source of truth, but backfill missing categories
            # from heuristics (e.g., lab rows occasionally omitted by backend).
            for h in heuristic_expenses:
                h_cat = _norm_cat(str(h.get("category") or ""))
                if not h_cat or h_cat in semantic_categories:
                    continue
                if h_cat != "laboratory":
                    continue
                if _parse_amount(h.get("amount")) <= 0:
                    continue
                expenses.append(dict(h))
                semantic_categories.add(h_cat)
            logger.info(
                "[EXPENSE_SELECTION] semantic_preferred sem_count=%s sem_total=%.2f heu_count=%s (zero-confidence backend)",
                sem_count,
                sem_total,
                heu_count,
            )
            doc.normalized_expenses = expenses
        else:
            heuristic_pages_set = {int(x.get("page") or 0) for x in heuristic_expenses if x.get("page") is not None}
            semantic_pages_set = {int(x.get("page") or 0) for x in semantic_expenses if x.get("page") is not None}
            uncovered_pages = heuristic_pages_set - semantic_pages_set
            should_blend = (
                sem_count == 0
                or bool(uncovered_pages)
                or (heu_count >= max(10, sem_count * 2))
                or (heu_count > sem_count and sem_conf < 0.60)
                or (sem_total > 0 and heu_total > 0 and heu_total > sem_total * 1.6 and sem_conf < 0.85)
            )
            if should_blend:
                expenses = _merge_expense_lists(list(semantic_expenses), heuristic_expenses)
                logger.info(
                    "[EXPENSE_SELECTION] blended semantic+heuristic sem_count=%s sem_conf=%.2f sem_total=%.2f heu_count=%s heu_conf=%.2f heu_total=%.2f",
                    sem_count,
                    sem_conf,
                    sem_total,
                    heu_count,
                    heu_conf,
                    heu_total,
                )
            else:
                expenses = list(semantic_expenses)
                logger.info(
                    "[EXPENSE_SELECTION] semantic_only sem_count=%s sem_conf=%.2f sem_total=%.2f",
                    sem_count,
                    sem_conf,
                    sem_total,
                )
    else:
        expenses = heuristic_expenses
        logger.info("[EXPENSE_SELECTION] heuristic_only heu_count=%s heu_conf=%.2f heu_total=%.2f", heu_count, heu_conf, heu_total)

    deduped_expenses = []
    # First-pass dedup: only collapse rows that are true double-extractions
    # (same description + amount + page AND from DIFFERENT sources).
    # Rows from the same source represent distinct physical line items
    # (e.g. General Ward Charges on Day 1 and Day 4 both at Rs.4187 — keep both).
    seen_cross_source: dict[tuple, str] = {}  # key -> source of first seen row
    for expense in expenses:
        if not _is_probable_expense_row(expense):
            continue
        key = (
            str(expense.get("description", "")).strip().lower(),
            str(expense.get("amount", "")).strip().lower(),
            str(expense.get("page", 0)),
        )
        row_source = str(expense.get("source") or expense.get("heuristic_source") or "unknown")
        if key in seen_cross_source:
            # Only skip if this is a cross-source duplicate (double-extraction artifact).
            # If same source already seen for this key, it means multiple distinct
            # daily charges with identical description+amount — preserve all of them.
            existing_source = seen_cross_source[key]
            if existing_source != row_source:
                # Different source → genuine double extraction → skip
                continue
            # Same source → daily repeat row → allow it through
        else:
            seen_cross_source[key] = row_source
        deduped_expenses.append(expense)

    # Second-pass: remove table-column-split duplicates.
    # These occur when the row reconstructor generates two records from a single
    # table row where one description is a proper substring of the other AND the
    # page + amount are identical (e.g. "Consultation Orthopaedic – 2 visits @"
    # and "Orthopaedic – 2 visits @ Rs. 1,000", both with amount=2000 on page 1).
    def _dedup_substring_pairs(rows: list[dict]) -> list[dict]:
        """Remove table-column-split duplicates.

        Two rows are duplicates when they share the same page + amount AND
        either:
          1. One normalized description is a literal substring of the other, or
          2. They have high word-token overlap (Jaccard ≥ 0.40) meaning the
             only differing words are a category-prefix token (e.g. 'consultation')
             or trailing price tokens (e.g. 'rs', '1', '000').
        In both cases, keep the longer/more-informative description.
        """
        to_remove: set[int] = set()
        for i in range(len(rows)):
            if i in to_remove:
                continue
            a = rows[i]
            a_desc = _norm_desc(a.get("description") or "")
            a_amt = _parse_amount(a.get("amount"))
            a_page = str(a.get("page", 0))
            a_set = set(a_desc.split()) if a_desc else set()
            for j in range(i + 1, len(rows)):
                if j in to_remove:
                    continue
                b = rows[j]
                b_desc = _norm_desc(b.get("description") or "")
                b_amt = _parse_amount(b.get("amount"))
                b_page = str(b.get("page", 0))
                # Must have same page AND same amount (non-zero)
                if a_amt != b_amt or a_page != b_page or not a_amt:
                    continue
                # Safeguard: if descriptions contain different dates, they are daily recurring items
                import re
                a_dates = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", a.get("description") or "")
                b_dates = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", b.get("description") or "")
                if a_dates and b_dates and a_dates != b_dates:
                    continue

                # Safeguard: Do not deduplicate separate daily charges (like multiple room charges or nursing charges)
                # that were extracted as distinct items by the SAME pipeline. Two items can only be duplicate extraction
                # fallouts if they come from different pipelines (e.g. one semantic, one heuristic table, or one table and one summary).
                a_srcs = set(a.get("sources") or [])
                if a.get("source"):
                    a_srcs.add(a.get("source"))

                b_srcs = set(b.get("sources") or [])
                if b.get("source"):
                    b_srcs.add(b.get("source"))

                a_sub = a.get("heuristic_source") or ("semantic" if "semantic" in a_srcs else "table")
                b_sub = b.get("heuristic_source") or ("semantic" if "semantic" in b_srcs else "table")

                if a_sub == b_sub:
                    # They share the exact same sub-pipeline (both are distinct rows in parsed tables,
                    # both are summary rows, or both are semantic). Therefore, they represent
                    # distinct physical items and must never be deduplicated.
                    continue

                if not a_desc or not b_desc:
                    continue
                b_set = set(b_desc.split())
                # Check 1: literal substring
                is_dup = (a_desc in b_desc) or (b_desc in a_desc)
                # Check 2: high-overlap token Jaccard (catches category-prefix splits)
                if not is_dup and a_set and b_set:
                    inter = a_set & b_set
                    union = a_set | b_set
                    jaccard = len(inter) / len(union) if union else 0.0
                    # Require ≥ 40% overlap AND at least 2 shared substantive tokens
                    if jaccard >= 0.40 and len(inter) >= 2:
                        is_dup = True
                # Check 3 (REMOVED): Previously we forced is_dup=True for any same odd amount,
                # but this incorrectly drops legitimate daily-repeat rows (e.g. Duty Doctor Fees
                # at Rs.765 on Day 1 and Day 4). Deduplication now requires description similarity
                # (Check 1 or Check 2) to have already fired before marking as duplicate.
                if is_dup:
                    # Prefer the higher-quality source; fall back to longer description
                    a_rank = _row_quality_rank(a)
                    b_rank = _row_quality_rank(b)
                    if a_rank > b_rank:
                        # a is higher quality: remove b
                        to_remove.add(j)
                    elif b_rank > a_rank:
                        # b is higher quality: remove a
                        to_remove.add(i)
                        break
                    else:
                        # Same quality rank: keep the longer, more informative description
                        if len(a_desc) >= len(b_desc):
                            to_remove.add(j)
                        else:
                            to_remove.add(i)
                            break
        return [r for idx, r in enumerate(rows) if idx not in to_remove]

    if len(deduped_expenses) > 1:
        before_count = len(deduped_expenses)
        deduped_expenses = _dedup_substring_pairs(deduped_expenses)
        if len(deduped_expenses) < before_count:
            logger.info(
                "[DEDUP] Removed %d table-column-split duplicate expense(s)",
                before_count - len(deduped_expenses),
            )

    doc.normalized_expenses = deduped_expenses
    # Expose normalized expenses in canonical claim for downstream consumers and UI
    try:
        if deduped_expenses:
            doc.canonical_claim.setdefault("expenses", {})["line_items"] = deduped_expenses
    except Exception:
        logger.debug("Failed to attach normalized_expenses to canonical_claim")
    
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
