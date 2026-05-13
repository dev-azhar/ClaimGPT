import json
from types import SimpleNamespace
import os, sys
sys.path.insert(0, os.getcwd())
from services.parser_v2 import table_reconstructor as tr

with open('tmp/parser_debug/detected_regions.json','r',encoding='utf-8') as f:
    regs = json.load(f)
for r in regs:
    if r.get('region_id','').startswith('51745') and r.get('region_type')=='table':
        toks = []
        for t in r['tokens']:
            x0,y0,x1,y1 = t['bbox']
            tok = SimpleNamespace()
            tok.text = t['text']
            tok.x0 = float(x0); tok.y0 = float(y0); tok.x1 = float(x1); tok.y1 = float(y1)
            tok.width = tok.x1 - tok.x0
            tok.height = max(1.0, tok.y1 - tok.y0)
            tok.x_center = (tok.x0 + tok.x1)/2.0
            tok.y_center = (tok.y0 + tok.y1)/2.0
            toks.append(tok)
        stats = tr._token_stats(toks)
        print('STATS:', stats)
        print('\nTOKENS:')
        for t in toks:
            print(f" text={t.text!r} x0={t.x0} x1={t.x1} width={t.width} x_center={t.x_center}")
        raw = tr._cluster_tokens_into_rows(toks)
        print('RAW ROW COUNT:', len(raw))
        for i,row in enumerate(raw):
            ys = [(t.y0,t.y1) for t in row]
            print(' ROW',i,'tokens',len(row),'y ranges',ys)
        logical, merges = tr._merge_multiline_rows(raw, stats)
        print('LOGICAL ROW COUNT:', len(logical))
        for i,row in enumerate(logical):
            print(' LOG',i,'len',len(row),'y ranges',[(t.y0,t.y1) for t in row])
        cols = tr._cluster_columns(logical, stats)
        print('\nCOLUMNS:')
        for c in cols:
            print(c)
