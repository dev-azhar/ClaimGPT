import sys
sys.path.insert(0, '.')
from services.submission.app.db import SessionLocal
from services.submission.app.models import Claim, ParsedField
from services.parser.app.engine import parse_document

db = SessionLocal()

# Get last 3 claims
claims = db.query(Claim).order_by(Claim.created_at.desc()).limit(3).all()

print('[RE-PARSING LAST 3 CLAIMS WITH FIXED PATTERNS]\n')

for idx, claim in enumerate(claims, 1):
    print(f'[{idx}] Claim: {claim.id}')
    
    # Clear existing parsed fields
    deleted = db.query(ParsedField).filter(ParsedField.claim_id == claim.id).delete()
    db.commit()
    print(f'    Cleared {deleted} old parsed fields')
    
    # Get documents
    from services.submission.app.models import Document, OcrResult
    docs = db.query(Document).filter(Document.claim_id == claim.id).all()
    
    total_persisted = 0
    
    for doc in docs:
        # Get OCR text
        ocr = db.query(OcrResult).filter(OcrResult.document_id == doc.id).first()
        if not ocr or not ocr.text:
            print(f'    No OCR for {doc.id}')
            continue
        
        # Parse document
        print(f'    Parsing {doc.id}...')
        ocr_pages = [{"page_number": 1, "text": ocr.text}]
        result = parse_document(ocr_pages)
        
        # Persist all extracted fields
        for field_result in result.fields:
            pf = ParsedField(
                claim_id=claim.id,
                document_id=doc.id,
                field_name=field_result.field_name,
                field_value=str(field_result.field_value),
                model_version=field_result.model_version or "heuristic-v2",
                doc_type="BILL"
            )
            db.add(pf)
            total_persisted += 1
        
        db.commit()
        print(f'    ✓ Persisted {total_persisted} fields')

print('\n✓ Re-parsing complete!')

# Show results
print('\n[VERIFICATION]\n')
from services.submission.app.main import _gather_claim_data_full

for idx, claim in enumerate(claims, 1):
    print(f'\n[{idx}] Claim: {claim.id}')
    try:
        data = _gather_claim_data_full(db, claim)
        diagnosis = data.get('parsed_fields', {}).get('diagnosis') or data.get('parsed_fields', {}).get('primary_diagnosis')
        print(f'    ✓ Diagnosis: {diagnosis if diagnosis else "[NOT FOUND]"}')
        print(f'    ✓ Billed Total: Rs.{data.get("billed_total", 0)}')
        print(f'    ✓ Expense Total: Rs.{data.get("expense_total", 0)}')
        print(f'    ✓ Expense items: {len(data.get("expenses", []))}')
    except Exception as e:
        print(f'    ERROR: {str(e)[:100]}')

db.close()
print('\nDone!')
