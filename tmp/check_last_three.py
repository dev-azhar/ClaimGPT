import sys
sys.path.insert(0, '.')
from services.submission.app.db import SessionLocal
from services.submission.app.models import Claim, ParsedField
from services.submission.app.main import _gather_claim_data_full

db = SessionLocal()

# Get last 3 claims
claims = db.query(Claim).order_by(Claim.created_at.desc()).limit(3).all()

print('[LAST 3 UPLOADED DOCUMENTS]\n')
print('='*80)

for idx, claim in enumerate(claims, 1):
    print(f'\n[{idx}] Claim: {claim.id}')
    print(f'    Created: {claim.created_at}')
    print(f'    Status: {claim.status}')
    
    # Get parsed fields
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).all()
    print(f'    Parsed fields: {len(pf_rows)}')
    
    # Get submission data
    try:
        data = _gather_claim_data_full(db, claim)
        
        # Check diagnosis
        diagnosis = data.get('parsed_fields', {}).get('diagnosis') or data.get('parsed_fields', {}).get('primary_diagnosis')
        print(f'    Diagnosis: {diagnosis if diagnosis else "[NOT FOUND]"}')
        
        # Check billed total
        billed_total = data.get('billed_total', 0)
        expense_total = data.get('expense_total', 0)
        print(f'    Billed Total: Rs.{billed_total}')
        print(f'    Expense Total: Rs.{expense_total}')
        
        # List parsed fields
        print(f'    Available fields:')
        for key, val in list(data.get('parsed_fields', {}).items())[:10]:
            val_str = str(val)[:40] if val else '[empty]'
            print(f'      - {key}: {val_str}')
        
        remaining = len(data.get('parsed_fields', {})) - 10
        if remaining > 0:
            print(f'      ... and {remaining} more')
    except Exception as e:
        print(f'    ERROR: {str(e)[:80]}')

db.close()
