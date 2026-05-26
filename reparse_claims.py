#!/usr/bin/env python3
import json
from pathlib import Path
from services.parser_v2.pipeline import parse_document

# Re-parse claim 42f2ba06
print("=== RE-PARSING CLAIM 42f2ba06 ===")
p1 = Path('tmp/parser_debug/42f2ba06-ad90-4847-956b-b458bc9a4497_24df3b06-73dc-4620-9f0f-d96580f1ea7e.json')
obj1 = json.loads(p1.read_text(encoding='utf-8'))
all_tokens1 = [token for page in obj1['ocr_pages'] for token in page['tokens']]
doc1 = parse_document(all_tokens1, debug_dir='tmp/parser_debug/reparse_42f2ba06')
print("Expenses after reparse:")
expenses1 = doc1.canonical_claim.get('expenses', {}).get('line_items', [])
for i, e in enumerate(expenses1, 1):
    print(f"  {i}: {e.get('description')} | {e.get('amount')}")

# Re-parse claim 49b78148
print("\n=== RE-PARSING CLAIM 49b78148 ===")
p2 = Path('tmp/parser_debug/49b78148-a315-4770-8910-3b5207fa3881_6c41c808-150e-4976-9e91-5050947c3722.json')
obj2 = json.loads(p2.read_text(encoding='utf-8'))
all_tokens2 = [token for page in obj2['ocr_pages'] for token in page['tokens']]
doc2 = parse_document(all_tokens2, debug_dir='tmp/parser_debug/reparse_49b78148')
print("Expenses after reparse:")
expenses2 = doc2.canonical_claim.get('expenses', {}).get('line_items', [])
for i, e in enumerate(expenses2, 1):
    print(f"  {i}: {e.get('description')} | {e.get('amount')}")
