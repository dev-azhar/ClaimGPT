import sys
sys.path.insert(0, '.')
from services.submission.app.db import SessionLocal
from services.submission.app.models import Claim, ParsedField
from services.parser.app.engine import parse_document

db = SessionLocal()

# Get last 3 claims
claims = db.query(Claim).order_by(Claim.created_at.desc()).limit(3).all()

print('[RE-PARSING LAST 3 CLAIMS]\n')

for idx, claim in enumerate(claims, 1):
    print(f'[{idx}] Claim: {claim.id}')
    
    # Clear existing parsed fields
    db.query(ParsedField).filter(ParsedField.claim_id == claim.id).delete()
    db.commit()
    
    # Get documents
    from services.submission.app.models import Document, OcrResult
    docs = db.query(Document).filter(Document.claim_id == claim.id).all()
    
    total_fields = 0
    total_expenses = 0
    
    for doc in docs:
        # Get OCR text
        ocr = db.query(OcrResult).filter(OcrResult.document_id == doc.id).first()
        if not ocr:
            print(f'    No OCR for {doc.id}')
            continue
        
        # Parse document - pass as list with page number and text
        print(f'    Processing {doc.id}...')
        ocr_pages = [{"page_number": 1, "text": ocr.text}]
        result = parse_document(ocr_pages)
        
        # Extract fields from FieldResult objects
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
            total_fields += 1
        
        # Handle expenses (these come as FieldResult too with specific model_version)
        for exp in result.table_data.get("expenses", []) if result.table_data else []:
            # exp is likely a dict with description and amount
            desc = exp.get("description", exp.get("desc", "Other Charges"))
            amount = exp.get("amount", 0)
            pf = ParsedField(
                claim_id=claim.id,
                document_id=doc.id,
                field_name=desc,
                field_value=str(amount),
                model_version="expense-table-heuristic-v2",
                doc_type="BILL"
            )
            db.add(pf)
            total_expenses += 1
        
        db.commit()
        print(f'    ✓ Persisted {total_fields} fields + {total_expenses} expenses')

print('\nRe-parsing complete!')

# Show results
print('\n[VERIFICATION]\n')
from services.submission.app.main import _gather_claim_data_full

for idx, claim in enumerate(claims, 1):
    print(f'\n[{idx}] Claim: {claim.id}')
    try:
        data = _gather_claim_data_full(db, claim)
        diagnosis = data.get('parsed_fields', {}).get('diagnosis') or data.get('parsed_fields', {}).get('primary_diagnosis')
        print(f'    Diagnosis: {diagnosis if diagnosis else "[NOT FOUND]"}')
        print(f'    Billed Total: Rs.{data.get("billed_total", 0)}')
        print(f'    Expense Total: Rs.{data.get("expense_total", 0)}')
        print(f'    Expense items: {len(data.get("expenses", []))}')
    except Exception as e:
        print(f'    ERROR: {str(e)[:80]}')

db.close()
