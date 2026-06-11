import json
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from services.parser_v2.models import TableRegion
from services.parser_v2.schema_normalizer import normalize_tables

path = r"c:\Project\ClaimGPT\tmp\parser_debug\runtime\01_parser_v2_output.json"

with open(path, "r", encoding="utf-8") as f:
    doc_json = json.load(f)

reconstructed_tables = []
for t in doc_json.get("tables", []):
    reconstructed_tables.append(TableRegion.model_validate(t))

print(f"Loaded {len(reconstructed_tables)} tables.")

# Run normalize_tables and print why it skipped or what it extracted for each
# Let's inspect the normalize_tables code to debug it:
for table in reconstructed_tables:
    table_kind = getattr(table, "table_kind", None)
    rid = table.region_id
    page = table.page
    
    print(f"\n--- Checking Table {rid} (Page {page}, Kind {table_kind}) ---")
    if table_kind and str(table_kind).lower() in {"medications", "vitals", "lab_results", "lab_result", "diagnoses", "diagnosis", "generic_table"}:
        print(f"  -> Skipped: table_kind match")
        continue
        
    # Let's run header map logic
    rows_list = list(table.rows)
    header_map = {}
    header_texts = []
    
    import re
    for idx, candidate_row in enumerate(rows_list[:20]):
        candidate_cells = sorted(candidate_row.cells, key=lambda cell: float(cell.bbox[0]) if cell.bbox else 0.0)
        candidate_texts = [str(cell.text or "").strip().lower() for cell in candidate_cells]
        
        row_text_joined = " ".join(candidate_texts)
        if ":" in row_text_joined and any(lbl in row_text_joined for lbl in ["patient", "policy", "member", "date", "bill no", "admission", "discharge"]):
            continue
            
        header_terms = ["description", "item", "particular", "service", "drug", "medicine", "qty", "quantity", "rate", "price", "gross", "total", "payable", "net payable", "np", "net pay", "netpay"]
        header_like_count = 0
        for t_text in candidate_texts:
            for term in header_terms:
                if term == "np":
                    if re.search(r"\bnp\b", t_text):
                        header_like_count += 1
                        break
                else:
                    if re.search(r"\b" + re.escape(term), t_text):
                        header_like_count += 1
                        break
        if header_like_count >= 1:
            print(f"  -> Candidate header found at Row {idx}: {candidate_texts}")
            header_texts = candidate_texts
            break
            
    if header_texts:
        for idx, text in enumerate(header_texts):
            if not text:
                continue
            if any(re.search(r"\b" + re.escape(term), text) for term in ["description", "item", "particular", "service", "drug", "medicine"]):
                header_map.setdefault("description", idx)
            if any(re.search(r"\b" + re.escape(term), text) for term in ["qty", "quantity", "days"]):
                header_map.setdefault("qty", idx)
            if any(re.search(r"\b" + re.escape(term), text) for term in ["rate", "unit price", "price"]):
                header_map.setdefault("rate", idx)
            if any(re.search(r"\b" + re.escape(term), text) for term in ["gross", "total"]):
                header_map.setdefault("gross", idx)
            if any(re.search(r"\b" + re.escape(term), text) for term in ["net payable", "payable", "amount payable", "amt payable", "net pay", "netpay"]):
                header_map.setdefault("payable", idx)
            elif re.search(r"\bnp\b", text) or any(re.search(r"\b" + re.escape(term), text) for term in ["non-payable", "non payable"]):
                header_map.setdefault("np", idx)
            elif "amount" in text:
                header_map.setdefault("payable", idx)
                
    is_expense_like_header = bool(header_map and "description" in header_map and ("payable" in header_map or "gross" in header_map or "rate" in header_map))
    print(f"  -> header_map: {header_map}")
    print(f"  -> is_expense_like_header: {is_expense_like_header}")
    
    from services.parser_v2.schema_normalizer import _is_metadata_or_form_table, _is_checklist_or_status_table
    is_meta = _is_metadata_or_form_table(table)
    is_checklist = _is_checklist_or_status_table(table)
    print(f"  -> _is_metadata_or_form_table: {is_meta}")
    print(f"  -> _is_checklist_or_status_table: {is_checklist}")
    
    # Check medications/labs/vitals
    from services.parser_v2.semantic_extractor import _is_medications_table, _is_lab_results_table, _is_vitals_table
    print(f"  -> _is_medications_table: {_is_medications_table(table)}")
    print(f"  -> _is_lab_results_table: {_is_lab_results_table(table)}")
    print(f"  -> _is_vitals_table: {_is_vitals_table(table)}")
