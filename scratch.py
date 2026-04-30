import sys
import pprint
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')
Session = sessionmaker(bind=engine)
db = Session()

from services.submission.app.models import Claim, ParsedField, Document, OcrResult

latest_claim = db.query(Claim).order_by(Claim.created_at.desc()).first()
if latest_claim:
    print('Latest Claim ID:', latest_claim.id)
    fields = db.query(ParsedField).filter(ParsedField.claim_id == latest_claim.id).all()
    print('\nParsed Fields:')
    for f in fields:
        print(f'  {f.field_name}: {f.field_value} ({f.model_version})')
        
    docs = db.query(Document).filter(Document.claim_id == latest_claim.id).all()
    print('\nDocuments:')
    for d in docs:
        print(f'  Doc {d.id}: {d.file_name}')
        ocr = db.query(OcrResult).filter(OcrResult.document_id == d.id).order_by(OcrResult.page_number).all()
        for o in ocr:
            text = o.text if o.text else ""
            print(f'    Page {o.page_number} length: {len(text)}')
            print(f'    Text snippet: {text[:2000]}')
else:
    print('No claims found')
