import json
from pathlib import Path
from services.parser_v2.pipeline import parse_document

print('=== RE-PARSING CLAIM ebdde98f-10a1-44d5-909f-19045c2e4d63 ===')
p = Path('tmp/parser_debug/ebdde98f-10a1-44d5-909f-19045c2e4d63_e2a99148-ff3c-471e-bb4b-0dc5e57ee9e9.json')
obj = json.loads(p.read_text(encoding='utf-8'))
all_tokens = [token for page in obj['ocr_pages'] for token in page['tokens']]
doc = parse_document(all_tokens, debug_dir='tmp/parser_debug/reparse_test')
print('Expenses after reparse:')
expenses = doc.canonical_claim.get('expenses', {}).get('line_items', [])
for i, e in enumerate(expenses, 1):
    print(f'  {i}: {e.get("description")} | {e.get("amount")}')
print('Fields after reparse:')
fields = doc.canonical_claim.get('fields', [])
for f in fields:
    print(f'  {f.get("field")}: {f.get("value")}')