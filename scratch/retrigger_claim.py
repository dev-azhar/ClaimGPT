import sys
import os
import uuid

# Ensure root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.ingress.app.main import _enqueue_pipeline

claim_id = "b8b949d3-8029-4ab2-9cf1-b8458e0bb6f8"
print(f"Retriggering pipeline for claim {claim_id}...")
task_id = _enqueue_pipeline(claim_id)
print(f"Successfully enqueued pipeline. Task ID: {task_id}")
