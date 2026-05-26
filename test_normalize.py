import json
from services.parser_v2.schema_normalizer import normalize_tables
from services.parser_v2.models import TableRegion

with open('tmp/parser_debug/runtime/01_parser_v2_output.json') as f:
    data = json.load(f)

tables = [TableRegion(**t) for t in data.get('tables', [])]
expenses = normalize_tables(tables)
for e in expenses:
    if e.get('page') == 1:
        print("Page 1: " + str(e.get('description')) + " -> " + str(e.get('amount')))
