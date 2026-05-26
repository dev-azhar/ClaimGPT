import uuid
from services.coding.app.db import SessionLocal
from services.coding.app.models import MedicalEntity, MedicalCode, Claim, ParsedField

def inspect_claim(claim_str):
    db = SessionLocal()
    try:
        claim_id = uuid.UUID(claim_str)
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            print(f"--- Claim {claim_str} not found ---")
            return
        
        print(f"\n==================================================")
        print(f"Claim ID: {claim.id}")
        print(f"Status: {claim.status}")
        
        pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()
        print(f"Parsed Fields found: {len(pf_rows)}")
        for idx, pf in enumerate(pf_rows):
            print(f"  [{idx+1}] {pf.field_name}: {pf.field_value!r} (Page: {pf.source_page})")
        
        entities = db.query(MedicalEntity).filter(MedicalEntity.claim_id == claim_id).all()
        print(f"Medical Entities found: {len(entities)}")
        for i, ent in enumerate(entities):
            print(f"  [{i+1}] Entity Text: {ent.entity_text!r}, Type: {ent.entity_type}, Conf: {ent.confidence}")
            
        codes = db.query(MedicalCode).filter(MedicalCode.claim_id == claim_id).all()
        print(f"Medical Codes found: {len(codes)}")
        for idx, mc in enumerate(codes):
            print(f"  [{idx+1}] Code: {mc.code}, System: {mc.code_system}, Primary: {mc.is_primary}, Conf: {mc.confidence}")
            print(f"      Description: {mc.description}")
            
    finally:
        db.close()

if __name__ == "__main__":
    claims = [
        "253699a0-81f1-4011-9c1a-132e03c4cdf4",
        "66ad6449-a8ba-4265-bb25-61819cbcab3e",
        "ea78dafc-fd72-4068-b189-a20de318f537"
    ]
    for cid in claims:
        inspect_claim(cid)
