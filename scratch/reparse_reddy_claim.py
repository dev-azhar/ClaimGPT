import sys
from sqlalchemy import create_engine, text
import time

sys.path.insert(0, r"c:\Project\ClaimGPT")
from libs.shared.celery_app import celery_app

engine = create_engine('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')
CLAIM_ID = '29f56772-ce4c-47e8-911d-d9b23ada6c25'

def main():
    print(f"Clearing database records for claim_id={CLAIM_ID}...")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM parsed_fields WHERE claim_id = :cid"), {"cid": CLAIM_ID})
        conn.execute(text("UPDATE claims SET status = 'OCR_COMPLETED', canonical_json = NULL WHERE id = :cid"), {"cid": CLAIM_ID})
        conn.execute(text("DELETE FROM parse_jobs WHERE claim_id = :cid"), {"cid": CLAIM_ID})
        conn.commit()
    print("Database records cleared successfully.")
    
    print("Triggering Celery parser task...")
    res = celery_app.send_task(
        "services.shared_tasks.parser_task",
        args=({"claim_id": CLAIM_ID},),
        queue="parser_queue"
    )
    print(f"Parser task triggered successfully! Task ID: {res.id}")
    print("Waiting for task to complete...")
    
    # We will let the background task run and check the logs
    
if __name__ == "__main__":
    main()
