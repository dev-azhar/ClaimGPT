import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from libs.shared.models import Claim, Document, DocValidation, AuditLog

# Connection URL matching docker-compose.yml postgres service credentials
engine = create_engine("postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")
Session = sessionmaker(bind=engine)
session = Session()

try:
    claim_id = uuid.UUID("cde6b866-3b50-4892-b2c9-4573bd9943f8")
    claim = session.query(Claim).get(claim_id)
    if not claim:
        print("Claim not found.")
    else:
        print(f"Claim status: {claim.status}")

        print("\nDocuments:")
        docs = session.query(Document).filter(Document.claim_id == claim_id).all()
        for d in docs:
            print(f"- ID: {d.id}, name: {d.file_name}, hash: {d.content_hash[:10]}...")

        print("\nValidations:")
        vals = session.query(DocValidation).filter(DocValidation.claim_id == claim_id).all()
        for v in vals:
            print(f"- Doc ID: {v.document_id}, type: {v.doc_type}, status: {v.status}, patient_match: {v.patient_match}, patient_name: {v.patient_name}, issues: {v.issues}")

        print("\nAudit Logs:")
        logs = session.query(AuditLog).filter(AuditLog.claim_id == claim_id).order_by(AuditLog.created_at.desc()).limit(15).all()
        for l in logs:
            print(f"- Action: {l.action}, actor: {l.actor}, at: {l.created_at}, metadata: {l.audit_metadata}")
finally:
    session.close()
