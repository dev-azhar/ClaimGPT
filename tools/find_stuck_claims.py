#!/usr/bin/env python3
import json
import urllib.request
import urllib.error

BASE = "http://localhost:8000"

def get_json(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return json.load(resp)
    except Exception as e:
        print(f"ERROR requesting {path}: {e}")
        return None

claims = get_json('/ingress/claims')
if not claims or 'claims' not in claims:
    print('No claims or failed to fetch claims')
    raise SystemExit(1)

stuck = []
for c in claims['claims']:
    cid = c.get('id')
    prog = get_json(f'/ingress/claims/{cid}/progress')
    if not prog:
        continue
    pct = prog.get('percentage')
    if pct == 0:
        stuck.append({'claim': c, 'progress': prog})

if not stuck:
    print('No stuck claims at 0% found.')
else:
    print('STUCK CLAIMS:')
    print(json.dumps(stuck, indent=2))
