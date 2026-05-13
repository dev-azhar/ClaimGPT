import json,os,sys
sys.path.insert(0, os.getcwd())
from services.parser_v2.form_extractor import extract_fields
from services.parser_v2.models import Region, Token

with open('tmp/parser_debug/detected_regions.json','r',encoding='utf-8') as f:
    regs = json.load(f)

for r in regs:
    if r.get('region_type')!='patient_form':
        continue
    texts = ' '.join(t.get('text','') for t in r.get('tokens',[]))
    if 'Age' in texts or 'Age-' in texts or 'Age.' in texts:
        print('FOUND REGION', r.get('region_id'))
        toks = []
        for t in r.get('tokens',[]):
            bbox = t.get('bbox', [0,0,0,0])
            toks.append(Token(text=t.get('text',''), x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3]), page=r.get('page',1)))
        region = Region(region_id=r.get('region_id'), region_type=r.get('region_type'), bbox=r.get('bbox'), tokens=toks, page=r.get('page',1))
        fields = extract_fields(region)
        print('EXTRACTED FIELDS:')
        for f in fields:
            print(f.model_dump())
        break
else:
    print('No region with Age found')
