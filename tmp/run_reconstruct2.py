import json, os, sys
sys.path.insert(0, os.getcwd())
from services.parser_v2 import table_reconstructor as tr
from services.parser_v2 import models

with open('tmp/parser_debug/detected_regions.json','r',encoding='utf-8') as f:
    regs = json.load(f)
for r in regs:
    if r.get('region_id','').startswith('51745') and r.get('region_type')=='table':
        toks = []
        for t in r['tokens']:
            tok = models.Token(
                text=t['text'],
                x0=float(t['bbox'][0]), y0=float(t['bbox'][1]),
                x1=float(t['bbox'][2]), y1=float(t['bbox'][3]),
                page=t.get('page',1), document_id=t.get('document_id'), claim_id=t.get('claim_id')
            )
            toks.append(tok)
        region = models.Region(region_id=r['region_id'], region_type=r['region_type'], bbox=r['bbox'], tokens=toks, page=r.get('page',1), document_id=r.get('document_id'), claim_id=r.get('claim_id'))
        table = tr.reconstruct_table(region)
        print('TABLE COLUMNS:')
        for c in table.columns:
            print(c)
        print('\nROWS:')
        for row in table.rows:
            print(row.row_id, row.token_count, [c.text for c in row.cells])
