#!/usr/bin/env python3
import json
import logging
from pathlib import Path
from services.parser_v2.pipeline import parse_document

# Set up logging so we see pipeline execution progress
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

print("=== RE-PARSING CLAIM 66aa6518-01c2-45e8-862d-1380a810d292 ===")
p = Path('tmp/parser_debug/66aa6518-01c2-45e8-862d-1380a810d292_96d2f587-21ac-4043-987f-a7d48c09fa04.json')
if not p.exists():
    print(f"File not found: {p}")
    exit(1)

obj = json.loads(p.read_text(encoding='utf-8'))
all_tokens = []
for page in obj.get("ocr_pages", []):
    for t in page.get("tokens", []):
        t_copy = dict(t)
        t_copy["page"] = page.get("page_number", 1)
        all_tokens.append(t_copy)

doc = parse_document(all_tokens, debug_dir='tmp/parser_debug/reparse_66aa6518')
print("\n=== RE-PARSED EXPENSES ===")
expenses = doc.canonical_claim.get('expenses', {}).get('line_items', [])
for i, e in enumerate(expenses, 1):
    print(f"  {i:2d}: {e.get('description'):<45} | {e.get('amount'):>8} | Date: {e.get('date', 'None')}")

print(f"\nTotal expenses count: {len(expenses)}")
