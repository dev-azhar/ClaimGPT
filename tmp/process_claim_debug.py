import json, os, sys
sys.path.insert(0, os.getcwd())
from services.parser_v2 import table_reconstructor as tr
from services.parser_v2 import models

IN = 'tmp/parser_debug/detected_regions.json'
OUT_TABLES = 'tmp/parser_debug/reconstructed_tables.run.json'
OUT_COLUMNS = 'tmp/parser_debug/column_clusters.run.json'
OUT_ASSIGN = 'tmp/parser_debug/cell_assignments.run.json'
OUT_ROWS = 'tmp/parser_debug/reconstructed_rows.run.json'

with open(IN, 'r', encoding='utf-8') as f:
    regs = json.load(f)

reconstructed = []
all_columns = []
all_assignments = []
all_rows = []

for r in regs:
    if r.get('region_type') != 'table':
        continue
    # build tokens as models.Token
    toks = []
    for t in r.get('tokens', []):
        bbox = t.get('bbox', [0,0,0,0])
        tok = models.Token(
            text=t.get('text',''),
            x0=float(bbox[0]), y0=float(bbox[1]),
            x1=float(bbox[2]), y1=float(bbox[3]),
            page=t.get('page', 1),
            document_id=t.get('document_id'),
            claim_id=t.get('claim_id')
        )
        toks.append(tok)

    region = models.Region(
        region_id=r.get('region_id'),
        region_type=r.get('region_type'),
        bbox=r.get('bbox'),
        tokens=toks,
        page=r.get('page', 1),
        document_id=r.get('document_id'),
        claim_id=r.get('claim_id')
    )

    table = tr.reconstruct_table(region)
    # convert to plain dicts
    tdict = table.dict()
    # attach extra metadata if present
    tdict['raw_row_count'] = getattr(table, '__dict__', {}).get('raw_row_count', None)
    tdict['logical_row_count'] = getattr(table, '__dict__', {}).get('logical_row_count', None)
    tdict['cell_assignments'] = getattr(table, '__dict__', {}).get('cell_assignments', [])

    reconstructed.append(tdict)
    # columns
    for c in tdict.get('columns', []):
        c['table_id'] = r.get('region_id')
        all_columns.append(c)
    # assignments
    for a in tdict.get('cell_assignments', []):
        a['table_id'] = r.get('region_id')
        all_assignments.append(a)
    # rows summary
    for row in tdict.get('rows', []):
        all_rows.append({
            'table_id': r.get('region_id'),
            'row_id': row.get('row_id'),
            'token_count': row.get('token_count'),
            'cell_count': len(row.get('cells', [])),
            'bbox': row.get('bbox')
        })

# write outputs
os.makedirs('tmp/parser_debug', exist_ok=True)
with open(OUT_TABLES, 'w', encoding='utf-8') as f:
    json.dump(reconstructed, f, indent=2, ensure_ascii=False)
with open(OUT_COLUMNS, 'w', encoding='utf-8') as f:
    json.dump(all_columns, f, indent=2, ensure_ascii=False)
with open(OUT_ASSIGN, 'w', encoding='utf-8') as f:
    json.dump(all_assignments, f, indent=2, ensure_ascii=False)
with open(OUT_ROWS, 'w', encoding='utf-8') as f:
    json.dump(all_rows, f, indent=2, ensure_ascii=False)

print('WROTE:', OUT_TABLES, OUT_COLUMNS, OUT_ASSIGN, OUT_ROWS)
