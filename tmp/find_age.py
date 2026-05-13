import json
regs=json.load(open('tmp/parser_debug/detected_regions.json'))
for r in regs:
    for t in r.get('tokens',[]):
        if 'Age' in t.get('text',''):
            print(r.get('region_id'), r.get('region_type'), t.get('text'))
