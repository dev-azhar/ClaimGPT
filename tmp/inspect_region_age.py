import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

import json
from services.parser_v2.models import Region, Token
from services.parser_v2.form_extractor import extract_fields
regs=json.load(open('tmp/parser_debug/detected_regions.json'))
for r in regs:
    if r.get('region_type') == 'patient_form':
        print('FOUND',r.get('region_id'))
        toks=[]
        for t in r.get('tokens',[]):
            bbox=t.get('bbox')
            toks.append(Token(text=t.get('text',''), x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3]), page=r.get('page',1)))
        region=Region(region_id=r.get('region_id'), region_type=r.get('region_type'), bbox=r.get('bbox'), tokens=toks, page=r.get('page',1))
        fields=extract_fields(region)
        print('EXTRACTED:')
        for f in fields:
            print(f.model_dump())
        break
else:
    print('not found')
