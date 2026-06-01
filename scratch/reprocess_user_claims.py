import sys
from sqlalchemy import create_engine, text

sys.path.insert(0, r"c:\Project\ClaimGPT")
from libs.shared.celery_app import celery_app

engine = create_engine('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')

def reprocess_claim(claim_id, name):
    print(f"\n=========================================")
    print(f"REPROCESSING CLAIM: {name} ({claim_id})")
    print(f"=========================================")
    
    with engine.connect() as conn:
        # Clear old parsed fields
        conn.execute(text("DELETE FROM parsed_fields WHERE claim_id = :cid"), {"cid": claim_id})
        # Reset claim to state that allows re-parsing (keep OCR results)
        conn.execute(text("UPDATE claims SET status = 'OCR_COMPLETED', canonical_json = NULL WHERE id = :cid"), {"cid": claim_id})
        # Delete old parse jobs so a fresh one gets created
        conn.execute(text("DELETE FROM parse_jobs WHERE claim_id = :cid"), {"cid": claim_id})
        conn.commit()
    print("Database records cleared.")
    
    print("Triggering Celery parser task...")
    res = celery_app.send_task(
        "services.shared_tasks.parser_task",
        args=({"claim_id": claim_id},),
        queue="parser_queue"
    )
    print(f"Celery task sent! Task ID: {res.id}")

def main():
    reprocess_claim("1f99f0f4-1d67-4e6f-8d80-f1c8515b89d9", "Claim 1 (Double Expenses)")
    reprocess_claim("199c3791-4cbd-4851-bea8-94a298cfb47c", "Claim 2 (Missing/Unnecessary Expenses)")

if __name__ == "__main__":
    main()
