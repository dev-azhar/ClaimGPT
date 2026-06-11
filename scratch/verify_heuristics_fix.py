import json
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from services.parser_v2.models import TableRegion

# Path to output json
path = r"c:\Project\ClaimGPT\tmp\parser_debug\runtime\01_parser_v2_output.json"

with open(path, "r", encoding="utf-8") as f:
    doc_json = json.load(f)

reconstructed_tables = []
for t in doc_json.get("tables", []):
    try:
        reconstructed_tables.append(TableRegion.model_validate(t))
    except Exception as e:
        print(f"Error validating table: {e}")

print(f"Loaded {len(reconstructed_tables)} tables from document JSON.")

from services.parser_v2.schema_normalizer import normalize_tables

extracted_expenses = normalize_tables(reconstructed_tables)

print(f"\n================ Extracted Expenses ({len(extracted_expenses)} items) ================")
total_amount = 0.0
for idx, exp in enumerate(extracted_expenses):
    desc = exp.get("description")
    amt_val = exp.get("amount")
    page = exp.get("page")
    try:
        amt = float(str(amt_val).replace(",", "").strip())
    except ValueError:
        amt = 0.0
    total_amount += amt
    print(f"Row {idx+1} [Page {page}]: {desc} -> Rs. {amt}")

print(f"\nTotal Calculated Amount: Rs. {total_amount}")
