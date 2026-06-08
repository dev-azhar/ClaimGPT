#!/usr/bin/env python3
import sys
import os
import uuid
from sqlalchemy import create_engine, text

# Ensure root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from libs.shared.celery_app import celery_app
from celery import chain
from services.shared_tasks import ocr_task, parser_task, coding_task, risk_task, validator_task, finalize_claim_task

# Under Docker, the database URL uses the internal 'postgres' hostname.
# Inlibs/shared/config.py, the default DB URL is loaded from env, but we can construct it using container environment.
db_url = os.getenv("DATABASE_URL", "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt")
engine = create_engine(db_url)

def reprocess_claim_full(claim_id, name):
    print(f"\n=========================================")
    print(f"FULL REPROCESSING CLAIM: {name} ({claim_id})")
    print(f"=========================================")

    cid = uuid.UUID(claim_id)

    with engine.connect() as conn:
        # 1. Delete old parsed fields
        conn.execute(text("DELETE FROM parsed_fields WHERE claim_id = :cid"), {"cid": cid})
        # 2. Delete old parse jobs
        conn.execute(text("DELETE FROM parse_jobs WHERE claim_id = :cid"), {"cid": cid})
        # 3. Delete old scan analyses
        conn.execute(text("DELETE FROM scan_analyses WHERE claim_id = :cid"), {"cid": cid})
        # 4. Delete old doc validations
        conn.execute(text("DELETE FROM document_validations WHERE claim_id = :cid"), {"cid": cid})
        # 5. Delete old ocr results
        # First find all doc IDs for the claim
        doc_rows = conn.execute(text("SELECT id FROM documents WHERE claim_id = :cid"), {"cid": cid}).fetchall()
        doc_ids = [row[0] for row in doc_rows]
        if doc_ids:
            conn.execute(text("DELETE FROM ocr_results WHERE document_id IN :doc_ids"), {"doc_ids": tuple(doc_ids)})
        # 6. Delete old ocr jobs
        conn.execute(text("DELETE FROM ocr_jobs WHERE claim_id = :cid"), {"cid": cid})
        # 7. Reset claim to UPLOADED status
        conn.execute(text("UPDATE claims SET status = 'UPLOADED', canonical_json = NULL WHERE id = :cid"), {"cid": cid})
        conn.commit()

    import time
    print("Waiting 3 seconds for database replication...")
    time.sleep(3)
    print("Database records cleared for full pipeline run.")

    print("Enqueuing Celery pipeline starting at OCR...")
    workflow_chain = chain(
        ocr_task.s({"claim_id": claim_id}),
        parser_task.s(),
        coding_task.s(),
        risk_task.s(),
        validator_task.s(),
        finalize_claim_task.s(),
    )
    res = workflow_chain.apply_async()
    print(f"Celery task chain enqueued! Task ID: {res.id}")
    return res.id

if __name__ == "__main__":
    # Reprocess the target claims
    reprocess_claim_full("29d187dd-b623-408b-8b91-0176baa8fa4c", "Claim 29d187dd")
    reprocess_claim_full("707895a8-a8dc-4eee-b89a-182fcb6fada8", "Claim 707895a8")
    reprocess_claim_full("28267d3c-957a-495b-b906-e3ab07fb61c9", "Claim 28267d3c")
