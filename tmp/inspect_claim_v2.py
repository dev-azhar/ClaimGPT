import uuid
import json
from services.submission.app.db import SessionLocal
from services.submission.app.models import Claim, Document, ParsedField, OcrResult
from services.submission.app.main import _gather_claim_data_full

db = SessionLocal()
cid = uuid.UUID('0d8664af-63a7-45bd-b9a8-5d6bbc445b86')
c = db.query(Claim).filter(Claim.id==cid).first()

if c:
    print('=== CLAIM ===')
    print(f'Status: {c.status}')
    
    # Get documents
    docs = db.query(Document).filter(Document.claim_id==cid).all()
    print(f'Documents: {len(docs)}')
    for d in docs:
        print(f'  - {d.file_name} ({d.file_type})')
    
    # Get OCR samples
    ocr_rows = db.query(OcrResult).filter(OcrResult.document_id.in_([d.id for d in docs])).all()
    if ocr_rows:
        print(f'OCR results: {len(ocr_rows)} pages')
        for ocr in ocr_rows[:3]:
            print(f'  Page {ocr.page_number}: {(ocr.text or "")[:200]}...')
    
    # Get parsed fields
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id==cid).all()
    print(f'Parsed fields: {len(pf_rows)}')
    for r in pf_rows[:20]:
        print(f'  {r.field_name}: {(r.field_value or "")[:50]} ({r.model_version})')
    
    # Get submission output
    data = _gather_claim_data_full(db, c)
    print(f'\nExpenses ({len(data.get("expenses", []))}):')
    for e in data.get('expenses', []):
        print(f'  {e.get("category")}: Rs.{e.get("amount")} (from {e.get("source_field")})')
else:
    print('Claim not found')

db.close()
