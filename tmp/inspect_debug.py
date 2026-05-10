import json
path = r'c:\Project\ClaimGPT\tmp\parser_debug\727df692-edb4-4329-a69c-1203cfd42896_301984ec-2a94-4ae5-b730-ce4df27e539c.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)
print('data keys', list(data.keys()))
print('fields type', type(data.get('fields')), 'count', len(data.get('fields', [])) if hasattr(data.get('fields'), '__len__') else 'n/a')
for f in (data.get('fields') or [])[:40]:
    print(f)
print('\nresults type', type(data.get('results')))
if isinstance(data.get('results'), list):
    print('results count', len(data.get('results')))
    for f in data.get('results')[:40]:
        print(f)
else:
    print('results contents', data.get('results'))
print('\ndetected_tables count', len(data['page_objects'][0]['detected_tables']))
if data['page_objects'][0]['detected_tables']:
    dt = data['page_objects'][0]['detected_tables'][0]
    print('header', dt.get('header'))
    print('rows', len(dt.get('rows', [])))
    for r in dt.get('rows', [])[:60]:
        print(r)
