import uuid
from services.coding.app.db import SessionLocal
from services.coding.app.models import ParsedField, Claim

def main():
    db = SessionLocal()
    try:
        claim_id = uuid.UUID("e7ad02f4-581c-4c68-8bde-0f278ab9db8e")
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            print("Claim not found!")
            return
        
        print(f"Claim status: {claim.status}")
        
        pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()
        print(f"Total ParsedField rows in DB for this claim: {len(pf_rows)}")
        
        for idx, pf in enumerate(pf_rows):
            print(f"[{idx+1}] ID: {pf.id}, field_name: {pf.field_name!r}, field_value: {pf.field_value!r}")
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
